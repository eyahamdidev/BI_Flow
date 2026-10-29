"""Integration test: the real ETL (load -> dbt build -> checks) on the committed 1% Olist sample.

Needs the repo checkout (configs/, scripts/, tests/fixtures/) and dbt: run it in the ETL container with the repo mounted:
    docker compose run --rm --no-deps -v "$PWD:/repo" -w /repo/services/etl etl python -m pytest -q
Skipped automatically when the fixture is not reachable (e.g. inside the plain image).
"""
import importlib.util
import json

import duckdb
import pytest
from app import config
from app.handlers import run
from biflow_contracts import RunRequest, RunResponse

ROOT = config.repo_root()
SAMPLE = ROOT / "tests" / "fixtures" / "olist_sample"
pytestmark = pytest.mark.skipif(not SAMPLE.is_dir(), reason="needs the repo checkout (tests/fixtures/olist_sample)")


@pytest.fixture(scope="module")
def etl_result(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(data))
    spec = importlib.util.spec_from_file_location("dev_seed_run", ROOT / "scripts" / "dev_seed_run.py")
    seed_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_mod)
    inputs = seed_mod.seed("olist", "tests/fixtures/olist_sample", "t1", data)
    # Feed the ETL the ingest-shaped files as if they were the cleaner's output: the ETL must cope with raw text
    # dates, duplicate geolocation rows and missing categories on its own.
    req = RunRequest(request_id="r", run_id="t1", dataset="olist", mode="run", config_ref="configs/datasets/olist.yaml",
                     inputs={k.replace("ingest.", "clean."): v for k, v in inputs.items()}, options={})
    out = run(req)
    yield out, data
    mp.undo()


def test_status_and_contract(etl_result):
    out, _ = etl_result
    resp = RunResponse(request_id="r", run_id="t1", module="etl", **out)  # validates against the frozen contract
    assert resp.status == "ok", (resp.error, resp.warnings)
    assert resp.metrics["dbt_models_failed"] == 0 and resp.metrics["dbt_tests_failed"] == 0


def test_reconciliation_one_row_per_order(etl_result):
    out, _ = etl_result
    assert out["metrics"]["reconciliation_ok"] is True
    assert out["metrics"]["rows"]["fact_orders"] == 1000


def test_marts_contract_columns_present(etl_result):
    _, data = etl_result
    cfg = config.load_dataset_yaml("configs/datasets/olist.yaml", "olist")
    with duckdb.connect(str(data / "runs/t1/03_etl/biflow.duckdb"), read_only=True) as con:
        have = {r[0] for r in con.execute("DESCRIBE fact_orders").fetchall()}
    assert set(cfg["marts"]["fact_orders"]) <= have


def test_warehouse_is_released_after_build(etl_result):
    _, data = etl_result
    con = duckdb.connect(str(data / "runs/t1/03_etl/biflow.duckdb"))  # read-WRITE: fails if anything still holds it
    assert con.execute("select count(*) from dim_date").fetchone()[0] > 600
    con.close()


def test_lineage_covers_every_model_and_carries_sql(etl_result):
    out, data = etl_result
    report = json.loads((data / "runs/t1/03_etl/etl_report.json").read_text())
    models = {m["name"] for m in report["models"]}
    events = {e["params"]["model"]: e for e in out["lineage_events"] if e["step"].startswith("dbt_") and "model" in e["params"]}
    assert models == set(events)
    assert "select" in events["fact_orders"]["params"]["sql"].lower()
    assert any(e["step"] == "reconcile" for e in out["lineage_events"])


def test_missing_input_is_bad_input():
    out = run(RunRequest(request_id="r", run_id="t2", dataset="olist", mode="run", config_ref="configs/datasets/olist.yaml",
                         inputs={}, options={}))
    assert out["status"] == "error" and out["error"]["code"] == "BAD_INPUT"
