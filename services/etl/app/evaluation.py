"""ETL evaluation (POST /v1/eval). Answers: are the numbers in the marts RIGHT, and is the model sound?

1. Build the warehouse from the committed 1% Olist sample (tests/fixtures/olist_sample), exactly like a real run.
2. Recompute 5 headline figures INDEPENDENTLY with pandas straight from the CSVs (no SQL, no dbt).
3. Compare: every figure must match to 1e-9 relative error.
Also reports dbt test pass rate, reconciliation and timing. Needs tests/fixtures mounted (docker-compose does it).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml
from biflow_contracts import RunRequest

from . import config

RUN_ID = "eval-etl"
TOL = 1e-9


def _read_csvs(cfg: dict[str, Any], src: Path) -> dict[str, pd.DataFrame]:
    """Like a CSV ingest: str-declared columns as text, the rest inferred by pandas."""
    out = {}
    for t, f in cfg["source"]["tables"].items():
        text = [c for c, spec in (cfg.get("expected_schema", {}).get(t) or {}).items()
                if (spec["type"] if isinstance(spec, dict) else spec) == "str"]
        out[t] = pd.read_csv(src / f, dtype={c: "string" for c in text}, low_memory=False)
    return out


def _pandas_truth(t: dict[str, pd.DataFrame]) -> dict[str, float]:
    o = t["orders"].copy()
    for c in ("order_purchase_timestamp", "order_delivered_customer_date", "order_estimated_delivery_date"):
        o[c] = pd.to_datetime(o[c])
    d = o[o.order_status == "delivered"]
    pay = t["order_payments"]
    r = t["order_reviews"].copy()
    r["review_answer_timestamp"] = pd.to_datetime(r["review_answer_timestamp"])
    latest = r.sort_values(["order_id", "review_answer_timestamp", "review_id"], ascending=[True, False, True]).drop_duplicates("order_id")
    delivered_reviews = latest[latest.order_id.isin(d.order_id)].review_score
    return {
        "revenue_delivered": float(pay[pay.order_id.isin(d.order_id)].payment_value.sum()),
        "orders_delivered": float(len(d)),
        "avg_delivery_days": float(((d.order_delivered_customer_date - d.order_purchase_timestamp).dt.total_seconds() / 86400).mean()),
        "late_rate": float((d.order_delivered_customer_date.dt.normalize() > d.order_estimated_delivery_date.dt.normalize()).mean()),
        "avg_review_score": float(delivered_reviews.mean()),
    }


SQL = """
select sum(payment_value), count(*), avg(delivery_days), avg(cast(is_late as integer)), avg(review_score)
from fact_orders where order_status = 'delivered'
"""


def run_eval() -> dict[str, Any]:
    from .handlers import run  # local import: handlers imports this module's package

    root = config.repo_root()
    sample = root / "tests" / "fixtures" / "olist_sample"
    if not sample.is_dir():
        return {"note": f"sample fixture not found at {sample} (mount ./tests/fixtures)"}
    cfg = yaml.safe_load((root / "configs" / "datasets" / "olist.yaml").read_text(encoding="utf-8"))

    tables = _read_csvs(cfg, sample)
    stage = config.data_dir() / "runs" / RUN_ID / "00_ingest"
    stage.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for name, df in tables.items():
        df.to_parquet(stage / f"{name}.parquet", index=False)
        inputs[f"clean.{name}"] = f"runs/{RUN_ID}/00_ingest/{name}.parquet"

    t0 = time.perf_counter()
    out = run(RunRequest(request_id="eval", run_id=RUN_ID, dataset="olist", mode="run",
                         config_ref="configs/datasets/olist.yaml", inputs=inputs, options={}))
    seconds = round(time.perf_counter() - t0, 2)
    if out["status"] == "error":
        return {"status": "error", "error": out["error"]}

    with duckdb.connect(str(config.data_dir() / "runs" / RUN_ID / config.STAGE_FOLDER / config.WAREHOUSE_NAME), read_only=True) as con:
        got = dict(zip(["revenue_delivered", "orders_delivered", "avg_delivery_days", "late_rate", "avg_review_score"],
                       (float(x) for x in con.execute(SQL).fetchone())))
    truth = _pandas_truth(tables)
    checks = {k: {"dbt": round(got[k], 6), "pandas": round(truth[k], 6),
                  "ok": abs(got[k] - truth[k]) <= TOL * max(1.0, abs(truth[k]))} for k in truth}
    m = out["metrics"]
    tests_total = m["dbt_tests_passed"] + m["dbt_tests_warned"] + m["dbt_tests_failed"]
    return {
        "kpi_checks_passed": f"{sum(c['ok'] for c in checks.values())}/{len(checks)}",
        "kpi_checks": checks,
        "dbt_tests_pass_rate": round(m["dbt_tests_passed"] / tests_total, 3) if tests_total else None,
        "dbt_tests_failed": m["dbt_tests_failed"],
        "reconciliation_ok": m["reconciliation_ok"],
        "seconds": seconds,
    }
