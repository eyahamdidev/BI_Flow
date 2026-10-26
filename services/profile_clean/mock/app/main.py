"""Mock profile_clean service — fixture responses only."""
from pathlib import Path

from biflow_contracts import RunRequest
from biflow_contracts.service_kit import create_app


def _stub(_req: RunRequest):
    raise NotImplementedError


app = create_app(
    module="profile_clean",
    handlers={"profile": _stub, "clean": _stub},
    mock_dir=Path(__file__).parent.parent,
    lineage_steps=["profile_tables", "translate_category_names", "impute_product_weight"],
    prompt_versions={"profile_clean.suggest_advisory": "v2"},
    eval_fn=lambda: {"mock": True},
)
