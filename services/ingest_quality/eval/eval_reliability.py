"""Reliability Evaluation Benchmark for BO4.

Measures:
1. Schema-error detection rate on 20 corrupted inputs (missing column, wrong type, non-nullable).
2. Score sensitivity & monotonicity on injected defects of known size.
3. Reproducibility rate across identical runs.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure services/ingest_quality is in path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from app.ingest import execute_ingest
from app.quality import execute_score
from app.validation import execute_validate
from biflow_contracts import RunRequest


def run_benchmark() -> dict[str, Any]:
    """Runs inside the LIVE service (POST /v1/eval): it must leave the process exactly as it found it.
    The benchmark points DATA_DIR at a temporary folder; restore it afterwards, otherwise every later ingest writes
    into a deleted temp folder while still answering "ok" (seen in integration: profile then found no input)."""
    import os

    saved = os.environ.get("DATA_DIR")
    try:
        return _run_benchmark()
    finally:
        if saved is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = saved


def _run_benchmark() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        data_dir = tmp_dir / "data"
        raw_dir = data_dir / "raw" / "eval_ds"
        raw_dir.mkdir(parents=True)

        # Baseline clean dataset
        n_rows = 100
        orders_df = pd.DataFrame({
            "order_id": [f"ord_{i:04d}" for i in range(n_rows)],
            "customer_id": [f"cust_{i % 20:04d}" for i in range(n_rows)],
            "order_status": ["delivered"] * n_rows,
            "order_purchase_timestamp": ["2026-01-01 10:00:00"] * n_rows,
            "order_delivered_customer_date": ["2026-01-05 10:00:00"] * n_rows,
        })
        cust_df = pd.DataFrame({
            "customer_id": [f"cust_{i:04d}" for i in range(20)],
            "customer_state": ["SP"] * 20,
        })

        orders_df.to_csv(raw_dir / "orders.csv", index=False)
        cust_df.to_csv(raw_dir / "customers.csv", index=False)

        cfg_file = tmp_dir / "eval_ds.yaml"
        cfg_file.write_text(
            f"""
name: eval_ds
source:
  type: csv
  path: {raw_dir.as_posix()}
  tables:
    orders: orders.csv
    customers: customers.csv
expected_schema:
  orders:
    order_id: str
    customer_id: str
    order_status: str
  customers:
    customer_id: str
    customer_state: str
relationships:
  - {{from: orders.customer_id, to: customers.customer_id}}
quality_score:
  weights: {{completeness: 0.3, uniqueness: 0.2, validity: 0.2, consistency: 0.2, timeliness: 0.1}}
""",
            encoding="utf-8",
        )

        import os
        os.environ["DATA_DIR"] = str(data_dir)

        # 1. Test Schema Error Detection on 20 Corrupted Inputs
        detected = 0
        total_corruptions = 20

        ingest_dir = data_dir / "runs" / "eval-run" / "00_ingest"
        ingest_dir.mkdir(parents=True, exist_ok=True)

        for i in range(total_corruptions):
            corrupt_orders = orders_df.copy()
            if i % 3 == 0:
                # Missing column
                corrupt_orders = corrupt_orders.drop(columns=["customer_id"])
            elif i % 3 == 1:
                # Null in non-nullable column
                corrupt_orders.loc[0, "order_id"] = None
            else:
                # Missing table or wrong column
                corrupt_orders = corrupt_orders.rename(columns={"order_status": "wrong_col"})

            corrupt_orders.to_parquet(ingest_dir / "orders.parquet", index=False)
            cust_df.to_parquet(ingest_dir / "customers.parquet", index=False)

            req = RunRequest(
                request_id=f"req-eval-{i}",
                run_id="eval-run",
                dataset="eval_ds",
                mode="validate",
                config_ref=str(cfg_file),
            )
            resp = execute_validate(req)
            if resp.status == "error" and resp.error and resp.error.code == "SCHEMA_MISMATCH":
                detected += 1

        detection_rate = round(detected / total_corruptions, 2)

        # 2. Score Sensitivity Benchmark (monotonic drop on injected defect sizes)
        defect_levels = [0.0, 0.05, 0.10, 0.20, 0.35, 0.50]
        scores: list[float] = []

        for p in defect_levels:
            test_orders = orders_df.copy()
            # Inject nulls
            n_nulls = int(len(test_orders) * p)
            if n_nulls > 0:
                test_orders.loc[:n_nulls - 1, "order_status"] = None
                # Inject orphan FKs
                test_orders.loc[:n_nulls - 1, "customer_id"] = "unknown_cust"

            test_orders.to_parquet(ingest_dir / "orders.parquet", index=False)
            cust_df.to_parquet(ingest_dir / "customers.parquet", index=False)

            req = RunRequest(
                request_id=f"req-score-{p}",
                run_id="eval-run",
                dataset="eval_ds",
                mode="score",
                config_ref=str(cfg_file),
            )
            s_resp = execute_score(req)
            scores.append(s_resp.metrics["overall"])

        # Check monotonic decrease
        is_monotonic = all(scores[idx] >= scores[idx + 1] for idx in range(len(scores) - 1))
        correlation = round(float(np.corrcoef(defect_levels, scores)[0, 1]), 3)

        # 3. Reproducibility test
        orders_df.to_parquet(ingest_dir / "orders.parquet", index=False)
        cust_df.to_parquet(ingest_dir / "customers.parquet", index=False)
        req_r1 = RunRequest(request_id="r1", run_id="eval-run", dataset="eval_ds", mode="score", config_ref=str(cfg_file))
        req_r2 = RunRequest(request_id="r2", run_id="eval-run", dataset="eval_ds", mode="score", config_ref=str(cfg_file))
        res1 = execute_score(req_r1)
        res2 = execute_score(req_r2)
        reproducibility = 1.0 if res1.metrics == res2.metrics else 0.0

        return {
            "schema_error_detection_rate": detection_rate,
            "corrupted_inputs_tested": total_corruptions,
            "score_monotonicity": is_monotonic,
            "score_defect_correlation": correlation,
            "baseline_score": scores[0],
            "severely_corrupted_score": scores[-1],
            "reproducibility_rate": reproducibility,
        }


if __name__ == "__main__":
    results = run_benchmark()
    print("=== BO4 Reliability Benchmark Results ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
