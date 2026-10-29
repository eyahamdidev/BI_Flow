"""ETL (DuckDB + dbt) handler (BO1). Mode `run`.

    cleaned parquet  --load-->  raw.<table> in data/runs/<id>/03_etl/biflow.duckdb
                     --dbt build-->  staging views (generated)  ->  intermediate  ->  marts (fact/dim tables) + tests
                     --checks-->  marts contract columns, row reconciliation
                     --report-->  outputs, metrics, one lineage event per load / model / test batch

Rules (docs/RULES.md): inputs by reference (paths relative to DATA_DIR), outputs under data/runs/<id>/03_etl/,
lineage for every transformation, no LLM, no import of another service. A retry rebuilds from scratch.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from biflow_contracts import RunRequest

from . import config
from .dbt_run import run_build
from .staging import write_staging


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _event(run_id: str, step: str, **kw: Any) -> dict[str, Any]:
    return {"event_id": str(uuid.uuid4()), "run_id": run_id, "ts": _now(), "agent": "etl", "step": step,
            "method": "deterministic", **kw}


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"status": "error", "error": {"code": code, "message": message}, **extra}


def _fingerprint(con: duckdb.DuckDBPyConnection, table: str) -> str:
    """Hash of a table's CONTENT, independent of row order. SUM of row hashes (XOR would cancel out duplicated rows);
    HUGEINT avoids overflow; reduced to 64 bits for display."""
    total = con.execute(f'SELECT sum(hash(t)::HUGEINT) FROM "{table}" t').fetchone()[0] or 0
    return f"{total % (1 << 64):016x}"


def _pick_inputs(req: RunRequest, tables: list[str]) -> tuple[dict[str, str], list[str]]:
    """table -> parquet path. Prefers `<input_stage>.<table>` (default clean), as named by the gateway."""
    stage = req.options.get("input_stage", "clean")
    found, missing = {}, []
    for t in tables:
        key = f"{stage}.{t}"
        if key in req.inputs:
            found[t] = req.inputs[key]
        else:
            missing.append(key)
    return found, missing


def run(req: RunRequest) -> dict[str, Any]:
    t_start = time.perf_counter()
    try:
        cfg = config.load_dataset_yaml(req.config_ref, req.dataset)
    except FileNotFoundError as e:
        return _error("BAD_INPUT", str(e))
    tables = list(cfg.get("source", {}).get("tables", {}))
    marts_dir = config.resolve(cfg.get("etl", {}).get("marts_dir", f"configs/marts/{cfg.get('domain', req.dataset)}"))
    if not (marts_dir / "models").is_dir():
        return _error("BAD_INPUT", f"marts folder not found: {marts_dir}/models (set etl.marts_dir in the dataset YAML)")

    inputs, missing = _pick_inputs(req, tables)
    if missing:
        return _error("BAD_INPUT", f"missing inputs: {missing}")
    for t, rel in inputs.items():
        if not (config.data_dir() / rel).exists():
            return _error("BAD_INPUT", f"input file not found: {rel}")

    # Fresh output folder: a retry or --resume rebuilds everything instead of mixing two attempts.
    rel_out = f"runs/{req.run_id}/{config.STAGE_FOLDER}"
    out_dir = config.data_dir() / rel_out
    db_path = out_dir / config.WAREHOUSE_NAME
    project = out_dir / "dbt"
    shutil.rmtree(project, ignore_errors=True)
    db_path.unlink(missing_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    events: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 1) Load cleaned parquet into raw.<table>
    t0 = time.perf_counter()
    table_columns: dict[str, list[str]] = {}
    raw_rows: dict[str, int] = {}
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE SCHEMA raw")
        for t, rel in inputs.items():
            con.execute(f'CREATE TABLE raw."{t}" AS SELECT * FROM read_parquet(?)', [str(config.data_dir() / rel)])
            raw_rows[t] = con.execute(f'SELECT count(*) FROM raw."{t}"').fetchone()[0]
            table_columns[t] = [r[0] for r in con.execute(f'DESCRIBE raw."{t}"').fetchall()]
            events.append(_event(req.run_id, "load_raw", rule=f"read_parquet -> raw.{t}", rows_affected=raw_rows[t],
                                 inputs=[{"name": t, "path": rel, "rows": raw_rows[t]}],
                                 outputs=[{"name": f"raw.{t}", "path": f"{rel_out}/{config.WAREHOUSE_NAME}", "rows": raw_rows[t]}]))
    load_s = time.perf_counter() - t0

    # 2) Assemble this run's dbt project: template + generated staging + domain marts
    shutil.copytree(config.DBT_TEMPLATE, project)
    config_name = req.config_ref or f"configs/datasets/{req.dataset}.yaml"
    write_staging(cfg, table_columns, project, config_name)
    shutil.copytree(marts_dir / "models", project / "models" / "marts")
    if (marts_dir / "tests").is_dir():
        shutil.copytree(marts_dir / "tests", project / "tests", dirs_exist_ok=True)

    # 3) dbt build = run every model + every test, in dependency order
    t0 = time.perf_counter()
    res = run_build(project, db_path)
    dbt_s = time.perf_counter() - t0
    if not res.models:
        return _error("INTERNAL", "dbt build failed before running any model: " + "; ".join(res.errors)[:2000],
                      lineage_events=events)

    # 4) Row counts, marts contract, reconciliation
    with duckdb.connect(str(db_path), read_only=True) as con:
        built = {m["name"] for m in res.models if m["status"] == "success"}
        rows = {name: con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in built}
        contract_missing: dict[str, list[str]] = {}
        for mart, cols in (cfg.get("marts") or {}).items():
            if mart not in built:
                contract_missing[mart] = ["<model not built>"]
                continue
            have = {r[0] for r in con.execute(f'DESCRIBE "{mart}"').fetchall()}
            if missing_cols := [c for c in cols if c not in have]:
                contract_missing[mart] = missing_cols
        # Fingerprint = hash of each mart's CONTENT, independent of row order: same input + same config must give
        # the same fingerprints (reproducibility check for benchmarks and BO4).
        fingerprints = {name: _fingerprint(con, name) for name in sorted(built) if name.startswith(("fact_", "dim_"))}
        root = cfg.get("sample", {}).get("root", {"table": "orders", "key": "order_id"})
        recon = None
        if f"stg_{root['table']}" in built and f"fact_{root['table']}" in built:
            n_stg = con.execute(f'SELECT count(DISTINCT "{root["key"]}") FROM "stg_{root["table"]}"').fetchone()[0]
            recon = {"staging_distinct": n_stg, "fact_rows": rows[f"fact_{root['table']}"], "ok": n_stg == rows[f"fact_{root['table']}"]}

    # 5) Lineage: one event per model (with its compiled SQL), one for the test batch, one for reconciliation
    for m in res.models:
        events.append(_event(
            req.run_id, f"dbt_{m['layer']}", rule=f"dbt model {m['name']} ({m['materialized']})",
            rows_affected=rows.get(m["name"]),
            inputs=[{"name": d, "rows": rows.get(d, raw_rows.get(d))} for d in m["depends_on"]],
            outputs=[{"name": m["name"], "path": f"{rel_out}/{config.WAREHOUSE_NAME}", "rows": rows.get(m["name"])}],
            params={"model": m["name"], "status": m["status"], "seconds": m["seconds"], "sql": m["sql"]},
        ))
    by_status: dict[str, int] = {}
    for t in res.tests:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    events.append(_event(req.run_id, "dbt_tests", rule="dbt test (generated staging + domain marts)",
                         rows_affected=sum(t["failures"] or 0 for t in res.tests if t["status"] != "pass"),
                         params={"summary": by_status, "tests": [{k: t[k] for k in ("name", "status", "failures", "severity")} for t in res.tests]}))
    if recon:
        events.append(_event(req.run_id, "reconcile", rule=f"count(distinct {root['key']}) in stg_{root['table']} == count(*) in fact_{root['table']}",
                             rows_affected=abs(recon["staging_distinct"] - recon["fact_rows"]), params=recon))

    # 6) Status: error if a model failed or the contract is broken, partial if an error-level test failed
    for t in res.tests:
        if t["status"] == "warn":
            warnings.append(f"data check (warn) {t['name']}: {t['failures']} rows")
        elif t["status"] in ("fail", "error"):
            warnings.append(f"TEST FAILED {t['name']}: {t['failures']} rows")
    if recon and not recon["ok"]:
        warnings.append(f"reconciliation failed: {recon}")

    report = {"models": [{k: m[k] for k in ("name", "layer", "status", "seconds")} | {"rows": rows.get(m["name"])} for m in res.models],
              "tests": res.tests, "reconciliation": recon, "contract_missing": contract_missing,
              "seconds": {"load": round(load_s, 2), "dbt": round(dbt_s, 2)}}
    (out_dir / "etl_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    outputs = [
        {"name": "warehouse", "kind": "duckdb", "path": f"{rel_out}/{config.WAREHOUSE_NAME}", "label": "DuckDB with staging views + marts"},
        {"name": "etl_report", "kind": "json", "path": f"{rel_out}/etl_report.json"},
        {"name": "dbt_manifest", "kind": "json", "path": f"{rel_out}/dbt/target/manifest.json"},
        {"name": "dbt_run_results", "kind": "json", "path": f"{rel_out}/dbt/target/run_results.json"},
    ]
    marts_rows = {k: v for k, v in rows.items() if k.startswith(("fact_", "dim_"))}
    metrics = {
        "dbt_models": len(res.models),
        "dbt_models_failed": sum(m["status"] != "success" for m in res.models),
        "dbt_tests_passed": by_status.get("pass", 0),
        "dbt_tests_warned": by_status.get("warn", 0),
        "dbt_tests_failed": by_status.get("fail", 0) + by_status.get("error", 0),
        "reconciliation_ok": recon["ok"] if recon else None,
        "fingerprints": fingerprints,
        "rows": marts_rows,
        "seconds_load": round(load_s, 2),
        "seconds_dbt": round(dbt_s, 2),
        "seconds_total": round(time.perf_counter() - t_start, 2),
    }

    if contract_missing:
        return _error("SCHEMA_MISMATCH", f"marts contract broken (dataset YAML `marts:`): {contract_missing}",
                      outputs=outputs, metrics=metrics, warnings=warnings, lineage_events=events)
    if metrics["dbt_models_failed"]:
        return _error("INTERNAL", "dbt model(s) failed: " + "; ".join(res.errors)[:2000],
                      outputs=outputs, metrics=metrics, warnings=warnings, lineage_events=events)
    status = "partial" if metrics["dbt_tests_failed"] or (recon and not recon["ok"]) else "ok"
    return {"status": status, "outputs": outputs, "metrics": metrics, "warnings": warnings, "lineage_events": events}
