"""Semantic & KPI (catalog, RAG): owner BO5. Port 8105.

The uniform endpoints (/health, /v1/meta, /v1/run, /v1/eval) come from biflow_contracts.service_kit.
Implement the handlers in handlers.py; until then BIFLOW_MOCK=1 serves mock/<mode>.json.
"""
from pathlib import Path

from biflow_contracts.service_kit import create_app

from . import handlers as h
from .evaluation import run_eval

app = create_app(
    module="semantic_kpi",
    handlers={"compute": h.compute, "index": h.index, "map_question": h.map_question, "suggest_kpis": h.suggest_kpis},
    mock_dir=Path(__file__).parent.parent / "mock",
    lineage_steps=["compute_kpi", "compute_kpi_cut", "index_kpis"],
    prompt_versions={"semantic_kpi.map_question": "v1"},
    eval_fn=run_eval,  # retrieval Recall@1/@3, MRR on eval/kpi_questions.jsonl
)
