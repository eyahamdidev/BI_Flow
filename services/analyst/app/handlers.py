"""Analyst (+ dashboard config) handlers (BO6). Maths in analysis.py, stage logic in insights.py / dashboard.py."""
from biflow_contracts import RunRequest

from .dashboard import dashboard_config as _dashboard_config
from .insights import analyse as _analyse


def analyse(req: RunRequest) -> dict:
    """Trends, anomalies (MAD), driver decomposition (sums to delta), rule-table recommendations, fact-checked narratives."""
    return _analyse(req)


def dashboard_config(req: RunRequest) -> dict:
    """dashboard_config.json (tiles, charts, dimensions) from kpi_definitions + kpi_values + insights."""
    return _dashboard_config(req)
