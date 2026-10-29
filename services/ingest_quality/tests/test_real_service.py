from __future__ import annotations

import os
from pathlib import Path

from app.main import app
from fastapi.testclient import TestClient


def test_real_pipeline_modes(tmp_path: Path, monkeypatch):
    """Test ingest, validate, score running for real with BIFLOW_MOCK=0 on tiny sample dataset."""
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "sample"
    raw_dir.mkdir(parents=True)

    # 1. Write tiny sample CSVs
    (raw_dir / "orders.csv").write_text(
        "order_id,customer_id,order_status,order_purchase_timestamp,order_delivered_customer_date\n"
        "o1,c1,delivered,2026-01-01 10:00:00,2026-01-02 12:00:00\n"
        "o2,c2,delivered,2026-01-02 10:00:00,2026-01-03 14:00:00\n",
        encoding="utf-8",
    )
    (raw_dir / "customers.csv").write_text(
        "customer_id,customer_state\n"
        "c1,SP\n"
        "c2,RJ\n",
        encoding="utf-8",
    )

    # 2. Write dataset YAML
    cfg_file = tmp_path / "sample.yaml"
    cfg_file.write_text(
        f"""
name: sample
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

    monkeypatch.setenv("BIFLOW_MOCK", "0")
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    client = TestClient(app)

    # 1. Real Ingest
    r1 = client.post(
        "/v1/run",
        json={
            "request_id": "r-ingest",
            "run_id": "run-demo",
            "dataset": "sample",
            "mode": "ingest",
            "config_ref": str(cfg_file),
            "inputs": {},
            "options": {},
        },
    )
    assert r1.status_code == 200, r1.text
    resp1 = r1.json()
    assert resp1["status"] == "ok"
    assert resp1["metrics"]["tables"] == 2
    assert resp1["metrics"]["rows_total"] == 4

    # 2. Real Validate
    r2 = client.post(
        "/v1/run",
        json={
            "request_id": "r-val",
            "run_id": "run-demo",
            "dataset": "sample",
            "mode": "validate",
            "config_ref": str(cfg_file),
            "inputs": {},
            "options": {},
        },
    )
    assert r2.status_code == 200, r2.text
    resp2 = r2.json()
    assert resp2["status"] == "ok"
    assert resp2["metrics"]["schema_errors"] == 0

    # 3. Real Score
    r3 = client.post(
        "/v1/run",
        json={
            "request_id": "r-score",
            "run_id": "run-demo",
            "dataset": "sample",
            "mode": "score",
            "config_ref": str(cfg_file),
            "inputs": {},
            "options": {"stage": "before"},
        },
    )
    assert r3.status_code == 200, r3.text
    resp3 = r3.json()
    assert resp3["status"] == "ok"
    assert resp3["metrics"]["overall"] == 100.0

