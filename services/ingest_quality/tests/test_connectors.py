from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pandas as pd
import pytest
from app.connectors import APIConnector, CSVConnector, SQLConnector, get_connector
from app.ingest import execute_ingest
from biflow_contracts import RunRequest


def test_csv_connector(tmp_path: Path):
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text("id,val\n1,alpha\n2,beta\n", encoding="utf-8")

    cfg = {"type": "csv", "path": str(tmp_path), "tables": {"sample": "sample.csv"}}
    conn = get_connector(cfg, root_dir=tmp_path)
    assert isinstance(conn, CSVConnector)
    dfs = conn.load()
    assert "sample" in dfs
    assert len(dfs["sample"]) == 2
    assert list(dfs["sample"]["id"]) == [1, 2]


def test_sql_connector(tmp_path: Path):
    db_file = tmp_path / "test.db"
    con = sqlite3.connect(str(db_file))
    cur = con.cursor()
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    cur.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
    con.commit()
    con.close()

    cfg = {
        "type": "sql",
        "url": f"sqlite:///{db_file.as_posix()}",
        "tables": {"users": "SELECT * FROM users WHERE id = 1"},
    }
    conn = get_connector(cfg, root_dir=tmp_path)
    assert isinstance(conn, SQLConnector)
    dfs = conn.load()
    assert "users" in dfs
    assert len(dfs["users"]) == 1
    assert dfs["users"].iloc[0]["name"] == "Alice"


def test_api_connector(monkeypatch):
    # Mock httpx.Client.get
    def mock_get(self, url, params=None, headers=None):
        page = params.get("page", 1) if params else 1
        if page == 1:
            data = {"items": [{"id": 101, "item": "book"}, {"id": 102, "item": "pen"}], "has_next": True, "total": 3}
        elif page == 2:
            data = {"items": [{"id": 103, "item": "notebook"}], "has_next": False, "total": 3}
        else:
            data = {"items": [], "has_next": False, "total": 3}

        req = httpx.Request("GET", url)
        return httpx.Response(200, json=data, request=req)

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    cfg = {
        "type": "api",
        "base_url": "http://mock-api.local",
        "tables": {"items": {"endpoint": "/items", "page_size": 2}},
    }
    conn = get_connector(cfg)
    assert isinstance(conn, APIConnector)
    dfs = conn.load()
    assert "items" in dfs
    assert len(dfs["items"]) == 3
    assert list(dfs["items"]["id"]) == [101, 102, 103]


def test_execute_ingest(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "test_ds"
    raw_dir.mkdir(parents=True)
    (raw_dir / "orders.csv").write_text("order_id,val\nO1,100\nO2,200\n", encoding="utf-8")

    cfg_file = tmp_path / "dataset.yaml"
    cfg_file.write_text(
        f"""
name: test_ds
source:
  type: csv
  path: {raw_dir.as_posix()}
  tables:
    orders: orders.csv
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("DATA_DIR", str(data_dir))

    req = RunRequest(
        request_id="req-123",
        run_id="run-abc",
        dataset="test_ds",
        mode="ingest",
        config_ref=str(cfg_file),
    )

    resp = execute_ingest(req)
    assert resp.status == "ok"
    assert resp.metrics["tables"] == 1
    assert resp.metrics["rows_total"] == 2

    # Check that parquet and manifest exist
    ingest_dir = data_dir / "runs" / "run-abc" / "00_ingest"
    assert (ingest_dir / "orders.parquet").exists()
    assert (ingest_dir / "manifest.json").exists()

    df_out = pd.read_parquet(ingest_dir / "orders.parquet")
    assert len(df_out) == 2
    assert list(df_out["order_id"]) == ["O1", "O2"]

