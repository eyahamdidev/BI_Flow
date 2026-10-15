"""ETL (DuckDB + dbt) handlers (BO1). Replace each NotImplementedError with the real implementation.

Rules (docs/RULES.md): read inputs by reference (req.inputs paths are relative to DATA_DIR), write outputs under
data/runs/<run_id>/<stage>/, return lineage_events for every transformation, never import another service.
This module needs no LLM.
"""
from biflow_contracts import RunRequest, RunResponse  # noqa: F401


def run(req: RunRequest) -> RunResponse | dict:
    """Load cleaned parquet into DuckDB and run the dbt project (staging + star schema marts + tests). Join SQL is rendered from the dataset YAML `relationships:`."""
    raise NotImplementedError
