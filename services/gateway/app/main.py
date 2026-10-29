"""Gateway (BO1): /api/* for the dashboard and CLI. Port 8000."""
from __future__ import annotations

import json
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import runner

app = FastAPI(title="BIFlow gateway")


class RunBody(BaseModel):
    dataset: str = "olist"
    resume_run_id: str | None = None
    ingest_from: str | None = None  # DEV: reuse data/runs/<id>/00_ingest instead of the ingest module


class AskBody(BaseModel):
    run_id: str
    question: str


class ExplainBody(BaseModel):
    run_id: str
    kpi_id: str
    period: str
    compare_to: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "module": "gateway"}


@app.get("/v1/meta")
def meta() -> dict[str, Any]:
    return {"module": "gateway", "stages": [s["name"] for s in runner.load_graph()]}


@app.get("/api/graph")
def api_graph() -> dict[str, str]:
    """The pipeline graph as Mermaid text (the dashboard or docs can render it)."""
    return {"mermaid": runner.build_graph().get_graph().draw_mermaid()}


@app.post("/api/runs")
def start_run(body: RunBody) -> dict[str, str]:
    import uuid
    from datetime import datetime

    run_id = body.resume_run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    threading.Thread(
        target=runner.run_pipeline,
        kwargs=dict(dataset=body.dataset, run_id=run_id, resume=bool(body.resume_run_id), ingest_from=body.ingest_from),
        daemon=True,
    ).start()
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs() -> list[str]:
    d = runner.data_dir() / "runs"
    return sorted((p.name for p in d.iterdir() if p.is_dir()), reverse=True) if d.exists() else []


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    f = runner.data_dir() / "runs" / run_id / "run_manifest.json"
    if not f.exists():
        raise HTTPException(404, "run not found")
    return json.loads(f.read_text())


@app.post("/api/explain")
def api_explain(body: ExplainBody) -> dict[str, Any]:
    return runner.explain(body.run_id, body.kpi_id, body.period, body.compare_to)


@app.post("/api/ask")
def api_ask(body: AskBody) -> dict[str, Any]:
    """Question in plain words -> KPI id (BO5), so the dashboard can explain "sales last month"."""
    return runner.ask(body.run_id, body.question)
