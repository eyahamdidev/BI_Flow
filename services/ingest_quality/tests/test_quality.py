from __future__ import annotations

from pathlib import Path

import pandas as pd
from app.quality import execute_score
from biflow_contracts import RunRequest


def test_quality_score_dimensions(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    ingest_dir = data_dir / "runs" / "run-score" / "00_ingest"
    ingest_dir.mkdir(parents=True)

    # 1. Orders table
    orders_df = pd.DataFrame({
        "order_id": ["O1", "O2", "O3"],
        "customer_id": ["C1", "C2", "C3"],
        "order_purchase_timestamp": ["2026-01-01 10:00:00", "2026-01-02 10:00:00", "2026-01-03 10:00:00"],
        "order_delivered_customer_date": ["2026-01-05 10:00:00", "2026-01-06 10:00:00", "2026-01-07 10:00:00"],
    })
    orders_df.to_parquet(ingest_dir / "orders.parquet", index=False)

    # 2. Customers table
    cust_df = pd.DataFrame({
        "customer_id": ["C1", "C2", "C3"],
        "customer_state": ["SP", "RJ", "MG"],
    })
    cust_df.to_parquet(ingest_dir / "customers.parquet", index=False)

    cfg_file = tmp_path / "ds.yaml"
    cfg_file.write_text(
        """
name: ds
relationships:
  - {from: orders.customer_id, to: customers.customer_id}
quality_score:
  weights: {completeness: 0.30, uniqueness: 0.20, validity: 0.20, consistency: 0.20, timeliness: 0.10}
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    req = RunRequest(
        request_id="req-score-1",
        run_id="run-score",
        dataset="ds",
        mode="score",
        config_ref=str(cfg_file),
    )

    resp = execute_score(req)
    assert resp.status == "ok"
    assert "overall" in resp.metrics
    assert resp.metrics["completeness"] == 100.0
    assert resp.metrics["consistency"] == 100.0
    assert resp.metrics["timeliness"] == 100.0
    assert resp.metrics["overall"] == 100.0


def test_quality_score_monotonic_sensitivity_on_corruptions(tmp_path: Path, monkeypatch):
    """Verify that injecting nulls and orphan FKs monotonically reduces the score."""
    data_dir = tmp_path / "data"
    ingest_dir = data_dir / "runs" / "run-corrupt" / "00_ingest"
    ingest_dir.mkdir(parents=True)

    cfg_file = tmp_path / "ds.yaml"
    cfg_file.write_text(
        """
name: ds
relationships:
  - {from: orders.customer_id, to: customers.customer_id}
quality_score:
  weights: {completeness: 0.50, uniqueness: 0.10, validity: 0.10, consistency: 0.30, timeliness: 0.0}
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("DATA_DIR", str(data_dir))

    # Clean version
    orders_clean = pd.DataFrame({"order_id": ["O1", "O2", "O3", "O4"], "customer_id": ["C1", "C2", "C3", "C4"]})
    cust_clean = pd.DataFrame({"customer_id": ["C1", "C2", "C3", "C4"]})
    orders_clean.to_parquet(ingest_dir / "orders.parquet", index=False)
    cust_clean.to_parquet(ingest_dir / "customers.parquet", index=False)

    req = RunRequest(request_id="r1", run_id="run-corrupt", dataset="ds", mode="score", config_ref=str(cfg_file))
    resp1 = execute_score(req)
    score_clean = resp1.metrics["overall"]

    # Mild corruption: inject 1 null
    orders_mild = pd.DataFrame({"order_id": ["O1", "O2", "O3", "O4"], "customer_id": ["C1", None, "C3", "C4"]})
    orders_mild.to_parquet(ingest_dir / "orders.parquet", index=False)
    resp2 = execute_score(req)
    score_mild = resp2.metrics["overall"]

    # Severe corruption: inject 2 nulls + 2 orphan FKs (unknown customers)
    orders_severe = pd.DataFrame({"order_id": ["O1", None, None, "O4"], "customer_id": ["C1", "C99", "C98", "C4"]})
    orders_severe.to_parquet(ingest_dir / "orders.parquet", index=False)
    resp3 = execute_score(req)
    score_severe = resp3.metrics["overall"]

    # Monotonic drop check
    assert score_clean > score_mild > score_severe

