"""BO5 eval (POST /v1/eval): retrieval quality on eval/kpi_questions.jsonl (synonyms, typos, French, Portuguese).
Retrieval only (LLM off) so the number is deterministic: Recall@1, Recall@3, MRR, plus the embedder used."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import load_dataset
from .retrieval import retrieve

QUESTIONS = Path(__file__).resolve().parent.parent / "eval" / "kpi_questions.jsonl"


def run_eval() -> dict[str, Any]:
    cfg = load_dataset("configs/datasets/olist.yaml", "olist")
    rows = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    r1 = r3 = rr = 0.0
    misses, emb = [], None
    for row in rows:
        top, emb = retrieve(cfg, row["q"], k=3)
        ids = [t["kpi_id"] for t in top]
        r1 += ids[:1] == [row["kpi"]]
        r3 += row["kpi"] in ids
        rr += 1 / (ids.index(row["kpi"]) + 1) if row["kpi"] in ids else 0
        if ids[:1] != [row["kpi"]]:
            misses.append(f"{row['q']} -> {ids[0]} (want {row['kpi']})")
    n = len(rows)
    return {"questions": n, "recall_at_1": round(r1 / n, 3), "recall_at_3": round(r3 / n, 3), "mrr": round(rr / n, 3),
            "embedder": emb, "top1_misses": misses[:10]}
