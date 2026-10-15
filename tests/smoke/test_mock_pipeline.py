"""End-to-end smoke test on MOCK services: starts the six modules, runs the gateway pipeline, checks the manifest.

Needs the deps of the services to be importable in the current interpreter (CI installs fastapi/uvicorn/httpx/pyyaml
+ contracts). No LLM, no Ollama, no key.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PORTS = {"etl": 8101, "auditor": 8102, "profile_clean": 8103, "ingest_quality": 8104, "semantic_kpi": 8105, "analyst": 8106}


@pytest.fixture()
def services(tmp_path):
    env = {**os.environ, "BIFLOW_MOCK": "1", "FAKE_LLM": "1", "DATA_DIR": str(tmp_path)}
    procs: dict[str, subprocess.Popen] = {}

    def start(name):
        procs[name] = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORTS[name]), "--log-level", "warning"],
            cwd=ROOT / "services" / name, env=env,
        )

    for n in PORTS:
        start(n)
    deadline = time.time() + 30
    for n, p in PORTS.items():
        while time.time() < deadline:
            try:
                if httpx.get(f"http://localhost:{p}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            raise RuntimeError(f"{n} did not start")
    yield procs, tmp_path
    for p in procs.values():
        p.terminate()
    for p in procs.values():
        p.wait(timeout=10)


def _runner(tmp_path):
    sys.path.insert(0, str(ROOT / "services" / "gateway"))
    os.environ["DATA_DIR"] = str(tmp_path)
    from app import runner  # noqa: PLC0415

    return runner


def test_full_mock_pipeline(services):
    _, tmp = services
    m = _runner(tmp).run_pipeline("olist")
    bad = {k: v["status"] for k, v in m["stages"].items() if v["status"] != "ok"}
    assert m["status"] == "ok" and not bad, bad
    run_dir = tmp / "runs" / m["run_id"]
    assert (run_dir / "run_manifest.json").exists()
    events = [json.loads(line) for line in (run_dir / "lineage" / "events.jsonl").read_text().splitlines()]
    assert events and all(e["run_id"] == m["run_id"] for e in events)


def test_failure_still_runs_auditor(services):
    procs, tmp = services
    procs["analyst"].terminate()
    procs["analyst"].wait(timeout=10)
    m = _runner(tmp).run_pipeline("olist")
    st = {k: v["status"] for k, v in m["stages"].items()}
    assert m["status"] == "failed"
    assert st["analyse"] == "failed" and st["dashboard_config"] == "skipped"
    assert st["lineage_graph"] == "ok" and st["audit"] == "ok"  # the failure is still explained
