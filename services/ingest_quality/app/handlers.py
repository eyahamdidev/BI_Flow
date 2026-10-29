"""Ingest + Validate + Quality score handlers (BO4).

Rules (docs/RULES.md): read inputs by reference (req.inputs paths are relative to DATA_DIR), write outputs under
data/runs/<run_id>/<stage>/, return lineage_events for every transformation, never import another service.
This module needs no LLM.
"""
from biflow_contracts import RunRequest, RunResponse

from .ingest import execute_ingest
from .quality import execute_score
from .validation import execute_validate


def ingest(req: RunRequest) -> RunResponse | dict:
    """Read the dataset source (csv|sql|api from configs/datasets/<ds>.yaml) and write raw parquet + manifest to data/runs/<run_id>/00_ingest/."""
    return execute_ingest(req)


def validate(req: RunRequest) -> RunResponse | dict:
    """Run pandera schemas generated from `expected_schema` in the dataset YAML. Return SCHEMA_MISMATCH with a readable message on failure."""
    return execute_validate(req)


def score(req: RunRequest) -> RunResponse | dict:
    """Deterministic 0-100 data quality score per table and overall (completeness, uniqueness, validity, consistency, timeliness). options.stage = before|after."""
    return execute_score(req)
