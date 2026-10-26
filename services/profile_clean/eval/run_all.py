"""Run benchmarks; write results/benchmark_table.md and runs.jsonl."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

SEED = 42
os.environ.setdefault("FAKE_LLM", "1")

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(EVAL_DIR))
RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


def _find_mini() -> Path:
    candidates = [
        REPO / "services" / "profile_clean" / "tests" / "fixtures" / "olist_mini",
        REPO / "data" / "runs",
    ]
    for c in candidates:
        if (c / "products.parquet").exists():
            return c
        if c.name == "runs":
            for run in sorted(c.iterdir(), reverse=True):
                ing = run / "00_ingest"
                if (ing / "products.parquet").exists():
                    return ing
    return candidates[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()
    t0 = time.perf_counter()
    mini = _find_mini()
    if not list(mini.glob("*.parquet")):
        sys.path.insert(0, str(REPO / "services" / "profile_clean"))
        from tests.conftest import _build_olist_mini

        _build_olist_mini()
        mini = REPO / "services" / "profile_clean" / "tests" / "fixtures" / "olist_mini"
    corrupted = RESULTS / "corrupted"
    corrupted.mkdir(exist_ok=True)

    from make_corrupted import corrupt, load_tables

    if list(mini.glob("*.parquet")):
        tables = load_tables(mini)
        if tables:
            ctables, manifest = corrupt(tables)
            for n, df in ctables.items():
                df.to_parquet(corrupted / f"{n}.parquet", index=False)
            (corrupted / "ground_truth.json").write_text(json.dumps(manifest, indent=2))

    from bench_imputation import run as bench_imp

    from bench_outliers import run as bench_out

    from bench_llm_advisory import run_benchmark as bench_llm

    imp = bench_imp(mini if (mini / "products.parquet").exists() else corrupted)
    outl = bench_out(corrupted)
    llm = bench_llm()

    metrics = {
        "imputation": imp,
        "outliers": outl,
        "llm_advisory": llm,
        "silent_deletions_target": 0,
        "row_reconciliation_target_pct": 100,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "seed": SEED,
    }
    (RESULTS / "last_eval_metrics.json").write_text(json.dumps(metrics, indent=2))

    row = {
        "module": "profile_clean",
        "provider": os.getenv("LLM_PROVIDER", "fake"),
        "metrics": metrics,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with (RESULTS / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")

    md = [
        "# profile_clean benchmarks\n",
        f"- imputation: `{json.dumps(imp)}`\n",
        f"- outliers: `{json.dumps(outl)}`\n",
        f"- llm_advisory: `{json.dumps(llm)}`\n",
        "## Failed attempts\n",
        "- iterative imputer may fail on tiny samples (recorded in imputation.iterative.failed if any)\n",
        "- live LLM models not benchmarked when FAKE_LLM=1; run `make eval-live` after Ollama/API setup\n",
    ]
    (RESULTS / "benchmark_table.md").write_text("".join(md), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
