from __future__ import annotations

from pathlib import Path

import pandas as pd
from app.validation import execute_validate
from biflow_contracts import RunRequest


def test_validation_success(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    ingest_dir = data_dir / "runs" / "run-val" / "00_ingest"
    ingest_dir.mkdir(parents=True)

    df_orders = pd.DataFrame({
        "order_id": ["O1", "O2"],
        "customer_id": ["C1", "C2"],
        "order_status": ["delivered", "shipped"],
    })
    df_orders.to_parquet(ingest_dir / "orders.parquet", index=False)

    cfg_file = tmp_path / "ds.yaml"
    cfg_file.write_text(
        """
name: ds
expected_schema:
  orders:
    order_id: str
    customer_id: str
    order_status: str
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    req = RunRequest(
        request_id="req-1",
        run_id="run-val",
        dataset="ds",
        mode="validate",
        config_ref=str(cfg_file),
    )
    resp = execute_validate(req)
    assert resp.status == "ok"
    assert resp.metrics["schema_errors"] == 0
    assert resp.metrics["tables_checked"] == 1


def test_validation_schema_mismatch_missing_column(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    ingest_dir = data_dir / "runs" / "run-val" / "00_ingest"
    ingest_dir.mkdir(parents=True)

    # Missing customer_id
    df_orders = pd.DataFrame({
        "order_id": ["O1", "O2"],
        "order_status": ["delivered", "shipped"],
    })
    df_orders.to_parquet(ingest_dir / "orders.parquet", index=False)

    cfg_file = tmp_path / "ds.yaml"
    cfg_file.write_text(
        """
name: ds
expected_schema:
  orders:
    order_id: str
    customer_id: str
    order_status: str
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    req = RunRequest(
        request_id="req-2",
        run_id="run-val",
        dataset="ds",
        mode="validate",
        config_ref=str(cfg_file),
    )
    resp = execute_validate(req)
    assert resp.status == "error"
    assert resp.error is not None
    assert resp.error.code == "SCHEMA_MISMATCH"
    assert "customer_id" in resp.error.message
    assert "Column missing" in resp.error.message


def test_validation_schema_mismatch_non_nullable(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    ingest_dir = data_dir / "runs" / "run-val" / "00_ingest"
    ingest_dir.mkdir(parents=True)

    # Contains null in non-nullable column
    df_orders = pd.DataFrame({
        "order_id": ["O1", None],
        "customer_id": ["C1", "C2"],
    })
    df_orders.to_parquet(ingest_dir / "orders.parquet", index=False)

    cfg_file = tmp_path / "ds.yaml"
    cfg_file.write_text(
        """
name: ds
expected_schema:
  orders:
    order_id: {type: str, nullable: false}
    customer_id: str
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    req = RunRequest(
        request_id="req-3",
        run_id="run-val",
        dataset="ds",
        mode="validate",
        config_ref=str(cfg_file),
    )
    resp = execute_validate(req)
    assert resp.status == "error"
    assert resp.error is not None
    assert resp.error.code == "SCHEMA_MISMATCH"
    assert "nullable=False" in resp.error.message

