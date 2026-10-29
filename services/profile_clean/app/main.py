"""Profiler + Cleaner: owner BO3. Port 8103.

The uniform endpoints (/health, /v1/meta, /v1/run, /v1/eval) come from biflow_contracts.service_kit.
Implement the handlers in handlers.py; until then BIFLOW_MOCK=1 serves mock/<mode>.json.
"""
from pathlib import Path

from biflow_contracts.service_kit import create_app

from . import handlers as h

app = create_app(
    module="profile_clean",
    handlers={"profile": h.profile, "clean": h.clean},
    mock_dir=Path(__file__).parent.parent / "mock",
    lineage_steps=["profile_tables", "translate_category_names", "impute_product_weight"],
    prompt_versions={},  # e.g. {"profile_clean.example": "v1"}
    eval_fn=None,  # set to a function returning a metrics dict once eval/ exists
)
