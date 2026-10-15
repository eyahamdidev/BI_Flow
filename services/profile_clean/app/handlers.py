"""Profiler + Cleaner handlers (BO3). Replace each NotImplementedError with the real implementation.

Rules (docs/RULES.md): read inputs by reference (req.inputs paths are relative to DATA_DIR), write outputs under
data/runs/<run_id>/<stage>/, return lineage_events for every transformation, never import another service.
LLM steps use biflow_contracts.biflow_llm (chat_text / chat_json) and must have a no-LLM fallback.
"""
from biflow_contracts import RunRequest, RunResponse  # noqa: F401

# from biflow_contracts.biflow_llm import chat_text, chat_json, drain_calls

def profile(req: RunRequest) -> RunResponse | dict:
    """Profile every table (types, nulls, dupes, outliers, FK orphans). options.stage=before|after. Writes profile.json (+ optional profile.html)."""
    raise NotImplementedError


def clean(req: RunRequest) -> RunResponse | dict:
    """Rule layer (YAML) + ML layer (imputers/outliers) + advisory LLM layer (closed menu). Writes cleaned parquet, quality_log.json, review_queue.json. in - dropped = out."""
    raise NotImplementedError
