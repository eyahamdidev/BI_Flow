"""The ONE LLM helper for the whole team (spec section 2.4).

Plain httpx to any OpenAI-compatible endpoint: local Ollama (http://localhost:11434/v1) or an API key.
Switching is a .env change, never a code change.

    from biflow_contracts.biflow_llm import chat_text, chat_json, embed, drain_calls

    text = chat_text("analyst.narrative@v1", system="...", user="...", role="llm_main", temperature=0.3)
    obj  = chat_json("profile_clean.suggest@v1", MySchema, system="...", user="...", role="llm_fast")
    vecs = embed(["revenue", "sales"])
    resp.llm_calls = drain_calls()      # attach to your RunResponse

Env: LLM_PROVIDER (ollama|api), LLM_BASE_URL, LLM_API_KEY, BIFLOW_PROFILE (ollama|api|low_ram),
     LLM_MODEL_MAIN / LLM_MODEL_FAST (overrides), EMBED_PROVIDER (ollama|api|local),
     FAKE_LLM=1 (CI), BIFLOW_CACHE (sqlite path), BIFLOW_CONFIG_DIR.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, TypeVar

import httpx
import yaml
from pydantic import BaseModel, ValidationError

from .models import LLMCall

T = TypeVar("T", bound=BaseModel)

_calls = threading.local()


class LLMUnavailable(RuntimeError):
    """Raised when the endpoint cannot be reached or keeps failing. Callers fall back (spec rule 8)."""


# ---------------------------------------------------------------- config
def _find_models_yaml() -> Path | None:
    d = os.getenv("BIFLOW_CONFIG_DIR")
    if d and (Path(d) / "models.yaml").exists():
        return Path(d) / "models.yaml"
    here = Path.cwd().resolve()
    for p in [here, *here.parents]:
        f = p / "config" / "models.yaml"
        if f.exists():
            return f
    return None


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama")


def resolve_models() -> dict[str, str]:
    f = _find_models_yaml()
    cfg = yaml.safe_load(f.read_text()) if f else {}
    profile = os.getenv("BIFLOW_PROFILE", provider())
    prof = (cfg.get("profiles") or {}).get(profile, {})
    out = {
        "llm_main": os.getenv("LLM_MODEL_MAIN") or prof.get("llm_main", ""),
        "llm_fast": os.getenv("LLM_MODEL_FAST") or prof.get("llm_fast", ""),
        "embedder": prof.get("embedder") or (cfg.get("embedder_options") or {}).get(embed_provider(), "") or "",
    }
    out["provider"] = provider()
    return out


def embed_provider() -> str:
    return os.getenv("EMBED_PROVIDER", "ollama")


def _base_url() -> str:
    return os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'ollama')}", "Content-Type": "application/json"}


# ---------------------------------------------------------------- call log + cache
def _log(call: LLMCall) -> None:
    if not hasattr(_calls, "items"):
        _calls.items = []
    _calls.items.append(call)


def drain_calls() -> list[LLMCall]:
    items = getattr(_calls, "items", [])
    _calls.items = []
    return items


def _cache_conn() -> sqlite3.Connection:
    path = Path(os.getenv("BIFLOW_CACHE", ".cache/llm.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")
    return conn


def _key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _cache_get(k: str) -> str | None:
    with _cache_conn() as c:
        row = c.execute("SELECT v FROM c WHERE k=?", (k,)).fetchone()
    return row[0] if row else None


def _cache_put(k: str, v: str) -> None:
    with _cache_conn() as c:
        c.execute("INSERT OR REPLACE INTO c VALUES (?,?)", (k, v))


# ---------------------------------------------------------------- fake LLM (CI)
def _fake() -> bool:
    return os.getenv("FAKE_LLM") == "1"


def _fixture(prompt_id: str) -> str | None:
    """tests/fixtures/llm/<prompt_id>.(json|txt), searched upward from cwd."""
    safe = prompt_id.replace("@", "_").replace("/", "_")
    here = Path.cwd().resolve()
    for p in [here, *here.parents]:
        for ext in ("json", "txt"):
            f = p / "tests" / "fixtures" / "llm" / f"{safe}.{ext}"
            if f.exists():
                return f.read_text(encoding="utf-8")
    return None


# ---------------------------------------------------------------- HTTP with retry
def _post(path: str, payload: dict[str, Any], timeout: float = 60.0, retries: int = 4) -> dict[str, Any]:
    url = f"{_base_url()}{path}"
    delay = 1.0
    last: Exception | None = None
    for _ in range(retries):
        try:
            r = httpx.post(url, json=payload, headers=_headers(), timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After", delay))
                time.sleep(min(wait, 30))
                delay *= 2
                last = RuntimeError(f"HTTP {r.status_code}")
                continue
            if r.status_code == 400:
                raise ValueError(r.text)  # caller may downgrade structured-output mode
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            last = e
            time.sleep(delay)
            delay *= 2
    raise LLMUnavailable(str(last))


def _chat(messages: list[dict[str, str]], model: str, temperature: float, extra: dict[str, Any] | None = None) -> tuple[str, int | None]:
    payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "seed": 7}
    payload.update(extra or {})
    data = _post("/chat/completions", payload)
    return data["choices"][0]["message"]["content"], (data.get("usage") or {}).get("total_tokens")


# ---------------------------------------------------------------- public API
def chat_text(prompt_id: str, system: str, user: str, role: str = "llm_main", temperature: float = 0.2) -> str:
    models = resolve_models()
    model = models.get(role, "")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if _fake():
        _log(LLMCall(prompt_id=prompt_id, model="fake", provider="fake", cache_hit=True))
        return _fixture(prompt_id) or f"[FAKE_TEXT {prompt_id}]"
    k = _key(provider(), model, prompt_id, msgs, temperature)
    hit = _cache_get(k)
    if hit is not None:
        _log(LLMCall(prompt_id=prompt_id, model=model, provider=provider(), cache_hit=True))
        return hit
    t0 = time.perf_counter()
    text, tokens = _chat(msgs, model, temperature)
    _cache_put(k, text)
    _log(LLMCall(prompt_id=prompt_id, model=model, provider=provider(), tokens=tokens, ms=int((time.perf_counter() - t0) * 1000)))
    return text


def chat_json(prompt_id: str, schema: type[T], system: str, user: str, role: str = "llm_fast", temperature: float = 0.0) -> T:
    """Structured output with the fallback ladder, always validated by pydantic (retry max 2)."""
    models = resolve_models()
    model = models.get(role, "")
    if _fake():
        _log(LLMCall(prompt_id=prompt_id, model="fake", provider="fake", cache_hit=True))
        raw = _fixture(prompt_id)
        if raw is None:
            raise LLMUnavailable(f"FAKE_LLM: no fixture tests/fixtures/llm/{prompt_id}.json")
        return schema.model_validate_json(raw)

    msgs = [
        {"role": "system", "content": system + "\nReturn ONLY valid JSON matching this schema:\n" + json.dumps(schema.model_json_schema())},
        {"role": "user", "content": user},
    ]
    k = _key(provider(), model, prompt_id, msgs, temperature)
    hit = _cache_get(k)
    if hit is not None:
        try:
            out = schema.model_validate_json(hit)
            _log(LLMCall(prompt_id=prompt_id, model=model, provider=provider(), cache_hit=True))
            return out
        except ValidationError:
            pass

    ladder: list[dict[str, Any]] = [
        {"response_format": {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}},
        {"response_format": {"type": "json_object"}},
        {},
    ]
    rung = 0
    err_note = ""
    for _attempt in range(3):  # first try + 2 retries
        t0 = time.perf_counter()
        while True:
            try:
                text, tokens = _chat(msgs + ([{"role": "user", "content": err_note}] if err_note else []), model, temperature, ladder[rung])
                break
            except ValueError:  # provider rejected this structured-output mode -> next rung
                if rung >= len(ladder) - 1:
                    raise LLMUnavailable("provider rejected all structured-output modes") from None
                rung += 1
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            out = schema.model_validate_json(text)
            _cache_put(k, out.model_dump_json())
            _log(LLMCall(prompt_id=prompt_id, model=model, provider=provider(), tokens=tokens, ms=int((time.perf_counter() - t0) * 1000)))
            return out
        except ValidationError as e:
            err_note = f"Your previous answer was invalid: {e.errors()[:3]}. Return ONLY corrected JSON."
    raise LLMUnavailable(f"{prompt_id}: output failed validation 3 times")


def embed(texts: list[str]) -> list[list[float]]:
    ep = embed_provider()
    model = resolve_models()["embedder"]
    if _fake():
        return [[(b % 17) / 17 for b in hashlib.sha256(t.encode()).digest()[:16]] for t in texts]
    if ep == "local":
        from sentence_transformers import SentenceTransformer  # only in the BO5 container

        return SentenceTransformer(model).encode(texts).tolist()
    base = os.getenv("EMBED_BASE_URL") or _base_url()
    r = httpx.post(f"{base.rstrip('/')}/embeddings", json={"model": model, "input": texts}, headers=_headers(), timeout=60)
    r.raise_for_status()
    return [d["embedding"] for d in r.json()["data"]]
