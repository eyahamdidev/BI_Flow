"""Analyst (+ dashboard config) handlers (BO6). Replace each NotImplementedError with the real implementation.

Rules (docs/RULES.md): read inputs by reference (req.inputs paths are relative to DATA_DIR), write outputs under
data/runs/<run_id>/<stage>/, return lineage_events for every transformation, never import another service.
LLM steps use biflow_contracts.biflow_llm (chat_text / chat_json) and must have a no-LLM fallback.
"""
from biflow_contracts import RunRequest, RunResponse  # noqa: F401

# from biflow_contracts.biflow_llm import chat_text, chat_json, drain_calls

def analyse(req: RunRequest) -> RunResponse | dict:
    """Trend (slope + STL), anomalies (MAD baseline), driver decomposition (sums to delta), rule-table recommendations, LLM narrative from facts only. Writes insights.json + drivers.json."""
    raise NotImplementedError


def dashboard_config(req: RunRequest) -> RunResponse | dict:
    """Generate dashboard_config.json (tiles, charts, dimensions) from kpi_definitions.json + insights.json."""
    raise NotImplementedError
