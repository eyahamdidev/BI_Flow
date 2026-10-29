"""Analyst (+ dashboard config): owner BO6. Port 8106.

The uniform endpoints (/health, /v1/meta, /v1/run, /v1/eval) come from biflow_contracts.service_kit.
Implement the handlers in handlers.py; until then BIFLOW_MOCK=1 serves mock/<mode>.json.
"""
from pathlib import Path

from biflow_contracts.service_kit import create_app

from . import handlers as h
from .evaluation import run_eval

app = create_app(
    module="analyst",
    handlers={"analyse": h.analyse, "dashboard_config": h.dashboard_config},
    mock_dir=Path(__file__).parent.parent / "mock",
    lineage_steps=["detect_trends", "detect_anomalies", "decompose_drivers", "match_recommendations", "write_narratives", "dashboard_config"],
    prompt_versions={"analyst.narrative": "v1"},
    eval_fn=run_eval,  # planted-anomaly recall/precision + driver sums-to-delta
)
