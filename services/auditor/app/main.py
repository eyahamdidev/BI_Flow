"""Auditor (lineage, trace report, Explain): owner BO2. Port 8102.

The uniform endpoints (/health, /v1/meta, /v1/run, /v1/eval) come from biflow_contracts.service_kit.
Implement the handlers in handlers.py; until then BIFLOW_MOCK=1 serves mock/<mode>.json.
"""
from pathlib import Path

from biflow_contracts.service_kit import create_app

from . import handlers as h
from .eval_runner import eval_metrics
from .prose import explain_kpi_default

app = create_app(
    module="auditor",
    handlers={"graph": h.graph, "audit": h.audit, "explain": h.explain},
    mock_dir=Path(__file__).parent.parent / "mock",
    lineage_steps=["build_lineage_graph", "write_trace_report", "explain_kpi"],
    prompt_versions={"auditor.section_prose": "v3", "auditor.explain_kpi": explain_kpi_default(), "auditor.fact_judge": "v1"},
    eval_fn=eval_metrics,
)
