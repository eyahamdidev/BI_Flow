"""Shared fixtures and env for profile_clean tests."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
OLIST_MINI = FIXTURES / "olist_mini"


@pytest.fixture(scope="session", autouse=True)
def _fake_llm_env():
    os.environ["FAKE_LLM"] = "1"
    root = Path(__file__).resolve().parents[3]
    os.environ.setdefault("DATA_DIR", str(root / "data"))
    os.environ.setdefault("BIFLOW_CONFIG_DIR", str(root / "config"))


@pytest.fixture(autouse=True)
def default_mock_mode(request, monkeypatch):
    """Contract tests use fixtures; integration tests opt into real handlers via run_workspace."""
    if "run_workspace" in request.fixturenames:
        return
    monkeypatch.setenv("BIFLOW_MOCK", "1")


def _build_olist_mini() -> None:
    OLIST_MINI.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    n = 120
    orders = pd.DataFrame(
        {
            "order_id": [f"o{i:05d}" for i in range(n)],
            "customer_id": [f"c{i:05d}" for i in range(n)],
            "order_status": ["delivered"] * (n - 10) + ["shipped"] * 10,
            "order_purchase_timestamp": pd.date_range("2017-01-01", periods=n, freq="h").astype(str),
            "order_approved_at": pd.date_range("2017-01-01", periods=n, freq="h").astype(str),
            "order_delivered_carrier_date": pd.date_range("2017-01-02", periods=n, freq="h").astype(str),
            "order_delivered_customer_date": list(pd.date_range("2017-01-03", periods=n - 10, freq="h").astype(str))
            + [None] * 10,
            "order_estimated_delivery_date": pd.date_range("2017-01-04", periods=n, freq="h").astype(str),
        }
    )
    products = pd.DataFrame(
        {
            "product_id": [f"p{i:05d}" for i in range(50)],
            "product_category_name": ["pc_gamer" if i == 0 else ("unknown_cat" if i == 1 else "cama_mesa_banho") for i in range(50)],
            "product_name_lenght": rng.integers(10, 100, 50),
            "product_description_lenght": rng.integers(10, 500, 50),
            "product_photos_qty": rng.integers(1, 5, 50),
            "product_weight_g": [np.nan if i < 3 else float(rng.integers(100, 5000)) for i in range(50)],
            "product_length_cm": [np.nan if i == 3 else float(rng.integers(10, 100)) for i in range(50)],
            "product_height_cm": [10.0] * 50,
            "product_width_cm": [10.0] * 50,
        }
    )
    order_items = pd.DataFrame(
        {
            "order_id": [f"o{i:05d}" for i in range(n)],
            "order_item_id": list(range(1, n + 1)),
            "product_id": [f"p{i%50:05d}" for i in range(n)],
            "seller_id": [f"s{i%20:05d}" for i in range(n)],
            "price": [float(rng.uniform(10, 500)) for _ in range(n - 1)] + [-5.0],
            "freight_value": [float(rng.uniform(5, 50)) for _ in range(n)],
        }
    )
    reviews = pd.DataFrame(
        {
            "review_id": [f"r{i:05d}" for i in range(n)],
            "order_id": [f"o{i:05d}" for i in range(n)],
            "review_score": rng.integers(1, 6, n),
            "review_comment_title": ["ok"] * n,
            "review_comment_message": [None if i % 5 == 0 else "great" for i in range(n)],
            "review_creation_date": pd.date_range("2017-02-01", periods=n, freq="h").astype(str),
            "review_answer_timestamp": pd.date_range("2017-02-02", periods=n, freq="h").astype(str),
        }
    )
    reviews = pd.concat([reviews, reviews.iloc[[0]]], ignore_index=True)
    geo_n = 200
    geolocation = pd.DataFrame(
        {
            "geolocation_zip_code_prefix": [f"{i%50:05d}" for i in range(geo_n)],
            "geolocation_lat": rng.uniform(-30, -10, geo_n),
            "geolocation_lng": rng.uniform(-60, -40, geo_n),
            "geolocation_city": ["São Paulo" if i % 3 == 0 else "Rio" for i in range(geo_n)],
            "geolocation_state": ["SP"] * geo_n,
        }
    )
    translation = pd.DataFrame(
        {
            "product_category_name": ["cama_mesa_banho", "portateis_cozinha_e_preparadores_de_alimentos"],
            "product_category_name_english": ["bed_bath_table", "kitchen_portables"],
        }
    )
    customers = pd.DataFrame({"customer_id": [f"c{i:05d}" for i in range(n)], "customer_unique_id": [f"cu{i}" for i in range(n)], "customer_zip_code_prefix": "01310", "customer_city": "  sao paulo  ", "customer_state": "SP"})
    sellers = pd.DataFrame({"seller_id": [f"s{i:05d}" for i in range(20)], "seller_zip_code_prefix": "01310", "seller_city": "rio", "seller_state": "RJ"})
    payments = pd.DataFrame({"order_id": [f"o{i:05d}" for i in range(n)], "payment_sequential": 1, "payment_type": "credit_card", "payment_installments": 1, "payment_value": 100.0})
    for name, df in [
        ("orders", orders),
        ("products", products),
        ("order_items", order_items),
        ("order_reviews", reviews),
        ("geolocation", geolocation),
        ("category_translation", translation),
        ("customers", customers),
        ("sellers", sellers),
        ("order_payments", payments),
    ]:
        df.to_parquet(OLIST_MINI / f"{name}.parquet", index=False)


@pytest.fixture(scope="session")
def olist_mini_dir():
    if not (OLIST_MINI / "orders.parquet").exists():
        _build_olist_mini()
    return OLIST_MINI


@pytest.fixture
def run_workspace(tmp_path, olist_mini_dir, monkeypatch):
    monkeypatch.setenv("BIFLOW_MOCK", "0")
    run_id = "test-run-pc"
    ingest = tmp_path / "runs" / run_id / "00_ingest"
    ingest.mkdir(parents=True)
    for p in olist_mini_dir.glob("*.parquet"):
        df = pd.read_parquet(p)
        df.to_parquet(ingest / p.name, index=False)
    os.environ["DATA_DIR"] = str(tmp_path)
    return run_id, tmp_path
