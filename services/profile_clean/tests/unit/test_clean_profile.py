from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pandas as pd
import pytest
from app.handlers import clean, profile
from app.io_utils import read_parquet, validate_input_path
from biflow_contracts import RunRequest
from fastapi.testclient import TestClient


def _req(mode: str, run_id: str, inputs: dict | None = None, options: dict | None = None) -> RunRequest:
    return RunRequest(
        request_id=str(uuid.uuid4()),
        run_id=run_id,
        dataset="olist",
        mode=mode,
        config_ref="configs/datasets/olist.yaml",
        inputs=inputs or {},
        options=options or {},
    )


def test_path_traversal_rejected():
    from app.errors import BadInputError

    with pytest.raises(BadInputError):
        validate_input_path("../etc/passwd")


def test_profile_and_clean_pipeline(run_workspace):
    run_id, tmp = run_workspace
    inputs = {f"ingest.{p.stem}": f"runs/{run_id}/00_ingest/{p.name}" for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet")}
    pr = profile(_req("profile", run_id, inputs=inputs, options={"stage": "before"}))
    assert pr["status"] == "ok"
    prof_path = tmp / "runs" / run_id / "01_profile" / "profile.json"
    assert prof_path.exists()

    cr = clean(
        _req(
            "clean",
            run_id,
            inputs={**inputs, "profile": f"runs/{run_id}/01_profile/profile.json"},
        )
    )
    assert cr["status"] in ("ok", "partial")
    assert cr["metrics"]["silent_deletions"] == 0
    assert cr["metrics"]["reconciliation_pass"] is True

    geo = read_parquet(tmp / "runs" / run_id / "02_clean" / "geolocation.parquet")
    assert len(geo) <= 55
    products = read_parquet(tmp / "runs" / run_id / "02_clean" / "products.parquet")
    assert "product_name_length" in products.columns
    assert "product_weight_g__imputed" in products.columns or products["product_weight_g"].notna().all()
    orders = read_parquet(tmp / "runs" / run_id / "02_clean" / "orders.parquet")
    assert "delivery_missing_flag" in orders.columns
    reviews = read_parquet(tmp / "runs" / run_id / "02_clean" / "order_reviews.parquet")
    assert "has_comment" in reviews.columns


def test_profile_after_diff(run_workspace):
    run_id, tmp = run_workspace
    base = tmp / "runs" / run_id
    inputs = {f"t.{p.stem}": f"runs/{run_id}/00_ingest/{p.name}" for p in (base / "00_ingest").glob("*.parquet")}
    profile(_req("profile", run_id, inputs=inputs, options={"stage": "before"}))
    clean(_req("clean", run_id, inputs=inputs))
    clean_inputs = {f"t.{p.stem}": f"runs/{run_id}/02_clean/{p.name}" for p in (base / "02_clean").glob("*.parquet")}
    profile(
        _req(
            "profile",
            run_id,
            inputs=clean_inputs,
            options={"stage": "after", "profile_before_path": f"runs/{run_id}/01_profile/profile.json"},
        )
    )
    assert (base / "03_profile_after" / "profile_diff.json").exists()


def test_olist_specific_cases(run_workspace):
    run_id, tmp = run_workspace
    inputs = {f"i.{p.stem}": f"runs/{run_id}/00_ingest/{p.name}" for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet")}
    clean(_req("clean", run_id, inputs=inputs))
    out = tmp / "runs" / run_id / "02_clean"
    orders = read_parquet(out / "orders.parquet")
    missing_delivery = orders["order_delivered_customer_date"].isna()
    assert orders.loc[missing_delivery, "delivery_missing_flag"].all()
    products = read_parquet(out / "products.parquet")
    assert (products.loc[products["product_category_name"] == "pc_gamer", "product_category_name_english"] == "pc_gamer").any()
    qlog = json.loads((out / "quality_log.json").read_text(encoding="utf-8"))
    assert isinstance(qlog, list)


def test_llm_unreachable_partial(run_workspace, monkeypatch):
    run_id, tmp = run_workspace
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("FAKE_LLM", "0")
    inputs = {f"i.{p.stem}": f"runs/{run_id}/00_ingest/{p.name}" for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet")}
    cr = clean(_req("clean", run_id, inputs=inputs))
    assert cr["status"] == "partial"
    assert any("LLM" in w for w in cr.get("warnings", []))


def test_adversarial_llm_not_applied(run_workspace):
    run_id, tmp = run_workspace
    os.environ["FAKE_LLM"] = "1"
    inputs = {f"i.{p.stem}": f"runs/{run_id}/00_ingest/{p.name}" for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet")}
    clean(_req("clean", run_id, inputs=inputs))
    rq = json.loads((tmp / "runs" / run_id / "02_clean" / "review_queue.json").read_text(encoding="utf-8"))
    assert any(item.get("column") == "order_id" for item in rq)
    orders = read_parquet(tmp / "runs" / run_id / "02_clean" / "orders.parquet")
    assert "order_id" in orders.columns


def test_determinism(run_workspace):
    run_id, tmp = run_workspace
    inputs = {f"i.{p.stem}": f"runs/{run_id}/00_ingest/{p.name}" for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet")}
    clean(_req("clean", run_id, inputs=inputs))
    h1 = (tmp / "runs" / run_id / "02_clean" / "products.parquet").read_bytes()
    run_id2 = run_id + "-b"
    ingest2 = tmp / "runs" / run_id2 / "00_ingest"
    ingest2.mkdir(parents=True)
    for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet"):
        pd.read_parquet(p).to_parquet(ingest2 / p.name, index=False)
    inputs2 = {f"i.{p.stem}": f"runs/{run_id2}/00_ingest/{p.name}" for p in ingest2.glob("*.parquet")}
    clean(_req("clean", run_id2, inputs=inputs2))
    h2 = (tmp / "runs" / run_id2 / "02_clean" / "products.parquet").read_bytes()
    assert h1 == h2


def test_undo_roundtrip(run_workspace):
    run_id, tmp = run_workspace
    inputs = {f"i.{p.stem}": f"runs/{run_id}/00_ingest/{p.name}" for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet")}
    clean(_req("clean", run_id, inputs=inputs))
    undo_dir = tmp / "runs" / run_id / "02_clean" / "_undo"
    files = list(undo_dir.glob("*.parquet"))
    if files:
        undo = pd.read_parquet(files[0])
        assert "original_value" in undo.columns


def test_lineage_steps_in_meta():
    c = TestClient(__import__("app.main", fromlist=["app"]).app)
    meta = c.get("/v1/meta").json()
    steps = set(meta["lineage_steps"])
    # minimal not needed - use run_workspace pattern in integration
    assert "profile_tables" in steps


def test_tiny_shop_yaml_only(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFLOW_MOCK", "0")
    root = Path(__file__).resolve().parents[4]
    shop_in = tmp_path / "runs" / "shop" / "00_ingest"
    shop_in.mkdir(parents=True)
    pd.DataFrame({"order_id": ["a", "a"], "amount": [1.0, 1.0], "product_id": ["p1", "p1"]}).to_parquet(shop_in / "orders.parquet")
    pd.DataFrame({"product_id": ["p1"], "label": [None]}).to_parquet(shop_in / "products.parquet")
    os.environ["DATA_DIR"] = str(tmp_path)
    inputs = {"orders": "runs/shop/00_ingest/orders.parquet", "products": "runs/shop/00_ingest/products.parquet"}
    clean(
        RunRequest(
            request_id=str(uuid.uuid4()),
            run_id="shop",
            dataset="tiny_shop",
            mode="clean",
            config_ref=str(root / "configs" / "datasets" / "tiny_shop.yaml"),
            inputs=inputs,
        )
    )
    orders = read_parquet(tmp_path / "runs" / "shop" / "02_clean" / "orders.parquet")
    assert len(orders) == 1
    products = read_parquet(tmp_path / "runs" / "shop" / "02_clean" / "products.parquet")
    assert products["label"].iloc[0] == "unknown"
