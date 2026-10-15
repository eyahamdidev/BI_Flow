"""Auditor (lineage, trace report, Explain) handlers (BO2). Replace each NotImplementedError with the real implementation.

Rules (docs/RULES.md): read inputs by reference (req.inputs paths are relative to DATA_DIR), write outputs under
data/runs/<run_id>/<stage>/, return lineage_events for every transformation, never import another service.
LLM steps use biflow_contracts.biflow_llm (chat_text / chat_json) and must have a no-LLM fallback.
"""
from biflow_contracts import RunRequest, RunResponse  # noqa: F401

# from biflow_contracts.biflow_llm import chat_text, chat_json, drain_calls

def graph(req: RunRequest) -> RunResponse | dict:
    """Build lineage_graph.json (nodes/edges) from lineage/events.jsonl."""
    raise NotImplementedError


def audit(req: RunRequest) -> RunResponse | dict:
    """Structured trace report first, then LLM prose per section from a fact sheet + number fact-check. Writes trace_report.md/json."""
    raise NotImplementedError


def explain(req: RunRequest) -> RunResponse | dict:
    """options: kpi_id, period, compare_to. Build a fact sheet (definition + lineage path + drivers), LLM writes 3-5 sentences, fact-check; abstain if sheet empty."""
    raise NotImplementedError
