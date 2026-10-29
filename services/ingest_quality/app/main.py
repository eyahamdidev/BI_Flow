"""Ingest + Validate + Quality score: owner BO4. Port 8104.

The uniform endpoints (/health, /v1/meta, /v1/run, /v1/eval) come from biflow_contracts.service_kit.
Implement the handlers in handlers.py; until then BIFLOW_MOCK=1 serves mock/<mode>.json.
"""
from pathlib import Path

from biflow_contracts.service_kit import create_app

from . import handlers as h
from .mock_api import mock_api_app


def _eval_fn():
    try:
        from ..eval.eval_reliability import run_benchmark
        return run_benchmark()
    except Exception as e:
        return {"error": str(e)}


app = create_app(
    module="ingest_quality",
    handlers={"ingest": h.ingest, "validate": h.validate, "score": h.score},
    mock_dir=Path(__file__).parent.parent / "mock",
    lineage_steps=["ingest_csv", "ingest_sql", "ingest_api", "validate_schema", "score"],
    prompt_versions={},
    eval_fn=_eval_fn,
)

# Mount mock API server for API connector demos and integration tests
app.mount("/mock_api", mock_api_app)
