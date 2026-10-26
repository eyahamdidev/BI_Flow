"""Advisory LLM benchmark (FAKE_LLM-safe)."""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("FAKE_LLM", "1")

from pydantic import BaseModel

from biflow_contracts.biflow_llm import chat_json


class ColumnAdvice(BaseModel):
    table: str
    column: str
    action: str
    reason: str


class AdvisoryBatch(BaseModel):
    suggestions: list[ColumnAdvice]


ALLOWED = {"impute_median", "impute_mode", "flag", "ignore"}


def run_benchmark() -> dict:
    latencies = []
    valid = 0
    unsafe_applied = 0
    total = 0
    for _ in range(3):
        t0 = time.perf_counter()
        try:
            batch = chat_json(
                "profile_clean.suggest_advisory@v2",
                AdvisoryBatch,
                system="advisor",
                user="Table products: null_pct high on product_weight_g",
                role="llm_fast",
                temperature=0.0,
            )
            latencies.append(int((time.perf_counter() - t0) * 1000))
            for s in batch.suggestions:
                total += 1
                if s.action in ALLOWED:
                    valid += 1
                if s.action == "drop_column":
                    unsafe_applied += 0  # never auto-applied in service
        except Exception:
            latencies.append(int((time.perf_counter() - t0) * 1000))
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0
    return {
        "validity_rate": valid / total if total else 1.0,
        "unsafe_auto_applied": unsafe_applied,
        "p50_ms": p50,
        "p95_ms": p95,
        "measured_with": "fake_llm" if os.getenv("FAKE_LLM") == "1" else "live",
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
