"""KPI knowledge base (RAG): modes `index` and `map_question`.

Corpus = the KPI catalog (name, description, synonyms, caveats). Tiny (tens of entries), so the index rebuilds in
milliseconds whenever the embedder changes (spec 2.4 rule 5: the collection stores `embedder_name`).

Embedder: the team's shared embed() helper (EMBED_PROVIDER = ollama | api | local). If it is unavailable (Groq has no
embeddings endpoint; sentence-transformers is not installed in this image), we fall back to a built-in character
trigram embedding ("hashing-char3"): no download, deterministic, robust to typos ("revnue"). The name is recorded,
so results are always attributable.

Retrieval = hybrid: cosine on the stored vectors (ChromaDB) + exact word/synonym overlap. Top-1 is the no-LLM answer;
optionally the fast LLM picks one id from the shortlist (closed menu, validated JSON), never an id outside it.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any

import numpy as np
from pydantic import BaseModel

from .common import data_dir, event, load_catalog, load_dataset

HASH_DIM = 512
WORD = re.compile(r"[a-z0-9]+")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # ChromaDB: no network calls


def _norm(text: str) -> str:
    return " ".join(WORD.findall(text.lower()))


def hashing_embed(texts: list[str]) -> list[list[float]]:
    """Character trigrams (+ whole words) hashed into 512 dims, L2-normalised."""
    out = []
    for t in texts:
        v = np.zeros(HASH_DIM)
        s = f" {_norm(t)} "
        grams = [s[i:i + 3] for i in range(len(s) - 2)] + WORD.findall(s)
        for g in grams:
            h = int.from_bytes(hashlib.md5(g.encode()).digest()[:4], "little")
            v[h % HASH_DIM] += 1.0 if len(g) == 3 else 2.0
        n = np.linalg.norm(v)
        out.append((v / n if n else v).tolist())
    return out


def embedder() -> tuple[str, Any]:
    """(name, fn). Tries the shared helper once; falls back to hashing-char3."""
    try:
        from biflow_contracts.biflow_llm import embed, embed_provider, resolve_models

        embed(["probe"])
        return f"{embed_provider()}:{resolve_models().get('embedder')}", embed
    except Exception:  # noqa: BLE001  unavailable provider, missing package, no network
        return f"hashing-char3-{HASH_DIM}", hashing_embed


def doc_text(k: dict[str, Any]) -> str:
    return ". ".join(str(x) for x in [k.get("name"), k.get("description"), ", ".join(k.get("synonyms") or []),
                                     k.get("caveats") or ""] if x)


def _client():
    import chromadb

    path = data_dir() / ".chroma"
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def build_index(cfg: dict[str, Any], force: bool = False) -> dict[str, Any]:
    domain = cfg.get("domain", "default")
    catalog = load_catalog(cfg)
    name, fn = embedder()
    col_name = f"kpi__{domain}"
    client = _client()
    try:
        col = client.get_collection(col_name)
        meta = col.metadata or {}
        fresh = (meta.get("embedder_name") == name and meta.get("catalog_hash") == _catalog_hash(catalog)
                 and col.count() == len(catalog))
        if fresh and not force:
            return {"collection": col_name, "embedder_name": name, "rebuilt": False, "entries": col.count()}
        client.delete_collection(col_name)
    except Exception:  # noqa: BLE001  collection does not exist yet
        pass
    col = client.create_collection(col_name, metadata={"embedder_name": name, "catalog_hash": _catalog_hash(catalog),
                                                        "hnsw:space": "cosine"})
    docs = [doc_text(k) for k in catalog]
    col.add(ids=[k["id"] for k in catalog], documents=docs, embeddings=fn(docs),
            metadatas=[{"name": k.get("name", ""), "unit": k.get("unit", "")} for k in catalog])
    return {"collection": col_name, "embedder_name": name, "rebuilt": True, "entries": len(catalog)}


def _catalog_hash(catalog: list[dict[str, Any]]) -> str:
    return hashlib.sha256(repr([(k["id"], doc_text(k)) for k in catalog]).encode()).hexdigest()[:16]


def retrieve(cfg: dict[str, Any], question: str, k: int = 3) -> tuple[list[dict[str, Any]], str]:
    info = build_index(cfg)  # no-op when fresh
    name, fn = embedder()
    col = _client().get_collection(info["collection"])
    catalog = {x["id"]: x for x in load_catalog(cfg)}
    res = col.query(query_embeddings=fn([question]), n_results=min(len(catalog), max(k * 3, 5)))
    words = set(WORD.findall(question.lower()))
    scored = []
    for kid, dist in zip(res["ids"][0], res["distances"][0], strict=True):
        dense = 1.0 - float(dist)  # cosine similarity
        terms = set(WORD.findall(doc_text(catalog[kid]).lower()))
        syn_hit = any(_norm(s) and _norm(s) in _norm(question) for s in [catalog[kid].get("name", ""), *(catalog[kid].get("synonyms") or [])])
        lexical = len(words & terms) / math.sqrt(len(words) or 1)
        scored.append({"kpi_id": kid, "score": round(dense + 0.15 * lexical + (0.5 if syn_hit else 0.0), 4),
                       "dense": round(dense, 4), "synonym_match": syn_hit})
    scored.sort(key=lambda s: -s["score"])
    return scored[:k], name


class Pick(BaseModel):
    kpi_id: str
    reason: str = ""


def map_question(cfg: dict[str, Any], question: str, use_llm: bool = True) -> dict[str, Any]:
    shortlist, emb_name = retrieve(cfg, question, k=3)
    top = shortlist[0]
    result = {"kpi_id": top["kpi_id"], "confidence": top["score"], "method": "retrieval", "shortlist": shortlist,
              "embedder_name": emb_name}
    if not use_llm or len(shortlist) < 2 or shortlist[0]["score"] - shortlist[1]["score"] > 0.25:
        return result  # clear winner, or LLM off: retrieval top-1 (the no-LLM fallback)
    try:
        from biflow_contracts.biflow_llm import chat_json

        catalog = {x["id"]: x for x in load_catalog(cfg)}
        menu = "\n".join(f"- {s['kpi_id']}: {catalog[s['kpi_id']].get('name')}: {catalog[s['kpi_id']].get('description')}" for s in shortlist)
        pick = chat_json("semantic_kpi.map_question@v1", Pick,
                         system="You map a business question to exactly one KPI id from a closed menu. Answer with an id from the menu only.",
                         user=f"Question: {question}\nMenu:\n{menu}", role="llm_fast")
        if pick.kpi_id in {s["kpi_id"] for s in shortlist}:
            result.update(kpi_id=pick.kpi_id, method="retrieval+llm", llm_reason=pick.reason)
    except Exception as e:  # noqa: BLE001  rule 8: degrade to retrieval top-1
        result["llm_warning"] = f"LLM pick skipped: {type(e).__name__}"
    return result


def index(req: Any) -> dict[str, Any]:
    cfg = load_dataset(req.config_ref, req.dataset)
    info = build_index(cfg, force=bool(req.options.get("force")))
    return {"status": "ok", "metrics": info,
            "warnings": [] if not info["embedder_name"].startswith("hashing") else
            ["embedder unavailable for EMBED_PROVIDER; using built-in hashing-char3 embedding"],
            "lineage_events": [event(req.run_id, "index_kpis", rule=f"embed catalog -> chroma {info['collection']}",
                                     rows_affected=info["entries"], params=info)]}


def map_question_mode(req: Any) -> dict[str, Any]:
    q = (req.options.get("question") or "").strip()
    if not q:
        return {"status": "error", "error": {"code": "BAD_INPUT", "message": "options.question is required"}}
    cfg = load_dataset(req.config_ref, req.dataset)
    res = map_question(cfg, q, use_llm=req.options.get("use_llm", True))
    from biflow_contracts.biflow_llm import drain_calls

    return {"status": "ok", "metrics": res, "llm_calls": drain_calls(),
            "lineage_events": [event(req.run_id, "map_question", rule="hybrid retrieval top-3 (+ LLM pick)",
                                     method="llm_assisted" if res["method"].endswith("llm") else "deterministic",
                                     params={"question": q, "kpi_id": res["kpi_id"], "method": res["method"]})]}
