"""ETL (DuckDB + dbt): owner BO1. Port 8101.

The uniform endpoints (/health, /v1/meta, /v1/run, /v1/eval) come from biflow_contracts.service_kit.
Implement the handlers in handlers.py; until then BIFLOW_MOCK=1 serves mock/<mode>.json.
"""
from pathlib import Path

from biflow_contracts.service_kit import create_app

from . import handlers as h
from .evaluation import run_eval

app = create_app(
    module="etl",
    handlers={"run": h.run},
    mock_dir=Path(__file__).parent.parent / "mock",
    lineage_steps=["load_raw", "dbt_staging", "dbt_intermediate", "dbt_marts", "dbt_tests", "reconcile"],
    prompt_versions={},  # e.g. {"etl.example": "v1"}
    eval_fn=run_eval,  # app/evaluation.py: rebuild the sample, check 5 figures against independent pandas
)
