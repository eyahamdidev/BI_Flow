"""Semantic & KPI (catalog, RAG) handlers (BO5). Replace each NotImplementedError with the real implementation.

Rules (docs/RULES.md): read inputs by reference (req.inputs paths are relative to DATA_DIR), write outputs under
data/runs/<run_id>/<stage>/, return lineage_events for every transformation, never import another service.
LLM steps use biflow_contracts.biflow_llm (chat_text / chat_json) and must have a no-LLM fallback.
"""
from biflow_contracts import RunRequest, RunResponse  # noqa: F401

# from biflow_contracts.biflow_llm import chat_text, chat_json, drain_calls

def compute(req: RunRequest) -> RunResponse | dict:
    """Execute each KPI `sql` from configs/kpis/<domain>.yaml on biflow.duckdb. Writes kpi_values.parquet + kpi_definitions.json. Every query is a lineage event."""
    raise NotImplementedError


def index(req: RunRequest) -> RunResponse | dict:
    """Embed KPI definitions into Chroma collection kpi__<domain>; store embedder_name in metadata; rebuild on mismatch."""
    raise NotImplementedError


def map_question(req: RunRequest) -> RunResponse | dict:
    """options.question -> KPI id via retrieval top-k (+ optional LLM pick from shortlist). Fallback: top-1."""
    raise NotImplementedError


def suggest_kpis(req: RunRequest) -> RunResponse | dict:
    """New-dataset onboarding: schema -> retrieve similar KPIs -> LLM binds columns from the shortlist -> draft YAML for human review. Never auto-executed."""
    raise NotImplementedError
