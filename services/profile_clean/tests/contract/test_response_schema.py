from __future__ import annotations

import json
import uuid
from pathlib import Path

import jsonschema
from app.main import app
from fastapi.testclient import TestClient

SCHEMAS = Path(__file__).resolve().parents[4] / "contracts" / "schemas"


def test_run_response_jsonschema(run_workspace, monkeypatch):
    monkeypatch.setenv("BIFLOW_MOCK", "0")
    run_id, tmp = run_workspace
    c = TestClient(app)
    inputs = {p.stem: f"runs/{run_id}/00_ingest/{p.name}" for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet")}
    for mode in ("profile", "clean"):
        body = {
            "request_id": str(uuid.uuid4()),
            "run_id": run_id,
            "dataset": "olist",
            "mode": mode,
            "config_ref": "configs/datasets/olist.yaml",
            "inputs": inputs,
            "options": {"stage": "before"},
        }
        r = c.post("/v1/run", json=body)
        assert r.status_code == 200
        schema = json.loads((SCHEMAS / "RunResponse.json").read_text(encoding="utf-8"))
        jsonschema.validate(r.json(), schema)
        for ev in r.json().get("lineage_events", []):
            jsonschema.validate(ev, json.loads((SCHEMAS / "LineageEvent.json").read_text(encoding="utf-8")))


def test_lineage_steps_complete(run_workspace, monkeypatch):
    monkeypatch.setenv("BIFLOW_MOCK", "0")
    run_id, tmp = run_workspace
    c = TestClient(app)
    meta = c.get("/v1/meta").json()
    allowed = set(meta["lineage_steps"])
    inputs = {p.stem: f"runs/{run_id}/00_ingest/{p.name}" for p in (tmp / "runs" / run_id / "00_ingest").glob("*.parquet")}
    r = c.post(
        "/v1/run",
        json={
            "request_id": str(uuid.uuid4()),
            "run_id": run_id,
            "dataset": "olist",
            "mode": "clean",
            "config_ref": "configs/datasets/olist.yaml",
            "inputs": inputs,
        },
    )
    for ev in r.json().get("lineage_events", []):
        assert ev["step"] in allowed
