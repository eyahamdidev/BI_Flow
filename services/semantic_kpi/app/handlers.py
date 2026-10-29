"""Semantic & KPI handlers (BO5). Implementations live in compute.py, retrieval.py, onboarding.py."""
from biflow_contracts import RunRequest

from .compute import compute as _compute
from .onboarding import suggest_kpis as _suggest
from .retrieval import index as _index
from .retrieval import map_question_mode as _map


def compute(req: RunRequest) -> dict:
    """Execute each KPI `sql` (total + dimension cuts) on the warehouse -> kpi_values.parquet + kpi_definitions.json."""
    return _compute(req)


def index(req: RunRequest) -> dict:
    """Embed KPI definitions into Chroma collection kpi__<domain>; embedder_name in metadata; rebuild on mismatch."""
    return _index(req)


def map_question(req: RunRequest) -> dict:
    """options.question -> KPI id: hybrid retrieval top-3, optional LLM pick from the shortlist, fallback top-1."""
    return _map(req)


def suggest_kpis(req: RunRequest) -> dict:
    """New dataset -> draft KPI YAML (column roles + templates + closest existing KPI). Never auto-executed."""
    return _suggest(req)
