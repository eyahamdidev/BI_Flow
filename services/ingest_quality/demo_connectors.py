"""Demo showing the three BO4 connectors in action: CSV, SQL, and API.

Usage:
    python demo_connectors.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure current service can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.connectors import get_connector
from app.mock_api import mock_api_app


def demo_csv():
    print("\n--- 1. CSV Connector Demo ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "orders.csv").write_text("order_id,price,status\nord_1,29.99,delivered\nord_2,49.50,shipped\n")
        cfg = {"type": "csv", "path": str(tmp_path), "tables": {"orders": "orders.csv"}}
        conn = get_connector(cfg, root_dir=tmp_path)
        dfs = conn.load()
        print(f"Loaded {len(dfs)} table(s):")
        for name, df in dfs.items():
            print(f"Table '{name}' shape: {df.shape}")
            print(df)


def demo_sql():
    print("\n--- 2. SQL Connector Demo (SQLite / DuckDB) ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "sales.db"
        con = sqlite3.connect(str(db_path))
        con.execute("CREATE TABLE products (product_id TEXT, category TEXT, price REAL)")
        con.execute("INSERT INTO products VALUES ('p1', 'electronics', 199.9), ('p2', 'books', 15.0)")
        con.commit()
        con.close()

        cfg = {
            "type": "sql",
            "url": f"sqlite:///{db_path.as_posix()}",
            "tables": {"products": "SELECT * FROM products WHERE price > 20"},
        }
        conn = get_connector(cfg, root_dir=tmp_path)
        dfs = conn.load()
        print(f"Loaded {len(dfs)} table(s):")
        for name, df in dfs.items():
            print(f"Table '{name}' shape: {df.shape}")
            print(df)


def demo_api():
    print("\n--- 3. API Connector Demo (Paginated JSON) ---")
    # Using TestClient as in-process HTTP mock
    import httpx
    client = TestClient(mock_api_app)

    # Monkeypatch httpx.Client to use TestClient
    original_client = httpx.Client

    class LocalClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return client

        def __exit__(self, *args):
            pass

    import app.connectors.api_connector as api_mod
    api_mod.httpx.Client = LocalClient  # type: ignore

    try:
        cfg = {
            "type": "api",
            "base_url": "http://testserver",
            "tables": {
                "orders": {"endpoint": "/orders", "page_size": 10},
                "customers": {"endpoint": "/customers", "page_size": 5},
            },
        }
        conn = get_connector(cfg)
        dfs = conn.load()
        print(f"Loaded {len(dfs)} table(s):")
        for name, df in dfs.items():
            print(f"Table '{name}' shape: {df.shape} (paginated rows retrieved)")
            print(df.head(3))
    finally:
        api_mod.httpx.Client = original_client


if __name__ == "__main__":
    print("=== Running BO4 Connectors Demo ===")
    demo_csv()
    demo_sql()
    demo_api()
    print("\n=== Demo Complete! ===")

