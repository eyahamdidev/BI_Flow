"""Run `dbt build` and read its artifacts.

dbt runs as a SEPARATE PROCESS (not dbtRunner in-process): dbt-duckdb caches its DuckDB connection at module
level, which kept the warehouse file locked after the build (we could not reopen it, and BO5 could not read it).
A subprocess releases every connection when it exits, and isolates dbt's global state between runs.

dbt writes two files we rely on (in <project>/target/):
  manifest.json     every node (model/test/source), its compiled SQL and what it depends on  -> lineage
  run_results.json  status, timing and failures for every node that ran                      -> metrics, warnings
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_lock = threading.Lock()  # one build at a time per service (DuckDB allows a single writer per file)


@dataclass
class DbtResult:
    success: bool
    models: list[dict[str, Any]] = field(default_factory=list)  # one per model: name, layer, status, seconds, sql, depends_on
    tests: list[dict[str, Any]] = field(default_factory=list)   # one per test: name, status, failures, severity, model
    errors: list[str] = field(default_factory=list)


def _layer(fqn: list[str]) -> str:
    # fqn = ['biflow', 'staging', 'stg_orders'] / ['biflow', 'marts', 'intermediate', 'int_x'] / ['biflow', 'marts', 'fact_orders']
    if "staging" in fqn:
        return "staging"
    if "intermediate" in fqn:
        return "intermediate"
    return "marts"


def run_build(project_dir: Path, duckdb_path: Path, timeout_s: int = 170) -> DbtResult:
    env = {**os.environ, "DUCKDB_PATH": str(duckdb_path), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    cmd = [
        shutil.which("dbt") or str(Path(sys.executable).with_name("dbt")), "build",
        "--project-dir", str(project_dir),
        "--profiles-dir", str(project_dir),
        "--target-path", str(project_dir / "target"),
        "--log-path", str(project_dir / "logs"),
        "--no-version-check",
    ]
    with _lock:
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return DbtResult(success=False, errors=[f"dbt build exceeded {timeout_s}s"])
    # exit code: 0 = all good, 1 = a model or test failed, 2 = dbt itself crashed (bad project, bad SQL syntax...)

    target = project_dir / "target"
    if not (target / "run_results.json").exists():
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
        return DbtResult(success=False, errors=["dbt produced no run_results.json:", *tail])

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    results = json.loads((target / "run_results.json").read_text(encoding="utf-8"))["results"]
    nodes = manifest["nodes"]

    out = DbtResult(success=proc.returncode == 0)
    for r in results:
        node = nodes.get(r["unique_id"], {})
        rtype = node.get("resource_type")
        if rtype == "model":
            out.models.append({
                "name": node["name"],
                "layer": _layer(node["fqn"]),
                "status": r["status"],
                "seconds": round(r.get("execution_time") or 0, 3),
                "materialized": node.get("config", {}).get("materialized"),
                "sql": node.get("compiled_code") or node.get("raw_code"),
                "depends_on": [d.split(".")[-1] for d in node.get("depends_on", {}).get("nodes", [])],
                "message": r.get("message"),
            })
        elif rtype == "test":
            attached = [d.split(".")[-1] for d in node.get("depends_on", {}).get("nodes", [])]
            out.tests.append({
                "name": node["name"],
                "status": r["status"],                   # pass | warn | fail | error | skipped
                "failures": r.get("failures"),
                "severity": node.get("config", {}).get("severity", "ERROR").lower(),
                "models": attached,
                "message": r.get("message"),
            })
        if r["status"] == "error":
            out.errors.append(f"{node.get('name', r['unique_id'])}: {r.get('message')}")
    return out
