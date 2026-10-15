"""Auditor (lineage, trace report, Explain): owner BO2. Port 8102.

The uniform endpoints (/health, /v1/meta, /v1/run, /v1/eval) come from biflow_contracts.service_kit.
Implement the handlers in handlers.py; until then BIFLOW_MOCK=1 serves mock/<mode>.json.
"""
from pathlib import Path

from biflow_contracts.service_kit import create_app

from . import handlers as h

app = create_app(
    module="auditor",
    handlers={"graph": h.graph, "audit": h.audit, "explain": h.explain},
    mock_dir=Path(__file__).parent.parent / "mock",
    lineage_steps=[],
    prompt_versions={},  # e.g. {"auditor.example": "v1"}
    eval_fn=None,  # set to a function returning a metrics dict once eval/ exists
)
