"""Data layer: reads run outputs from DATA_DIR/runs/<run_id>/..., falls back to bundled fixtures (demo mode)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@dataclass
class Bundle:
    source: str                      # "fixtures" or "run"
    run_id: str | None
    kpi_defs: list[dict]
    values: pd.DataFrame             # kpi_id, period, dimension, dimension_value, value
    insights: list[dict]
    quality: dict                    # {"before": {...}, "after": {...}}
    lineage: dict                    # {"nodes": [...], "edges": [...]}


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def list_runs() -> list[str]:
    d = data_dir() / "runs"
    return sorted((p.name for p in d.iterdir() if p.is_dir() and (p / "run_manifest.json").exists()), reverse=True) if d.exists() else []


def _json(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def _values(p_parquet: Path, p_csv: Path) -> pd.DataFrame:
    if p_parquet.exists():
        return pd.read_parquet(p_parquet)
    return pd.read_csv(p_csv)


def load(run_id: str | None = None) -> Bundle:
    """Real run if it has the artifacts, otherwise fixtures. Missing pieces fall back individually."""
    if run_id:
        r = data_dir() / "runs" / run_id
        have_kpi = (r / "04_kpi" / "kpi_values.parquet").exists()
        if have_kpi:
            qs = _json(r / "00_ingest" / "quality_score.json", None)
            return Bundle(
                source="run", run_id=run_id,
                kpi_defs=_json(r / "04_kpi" / "kpi_definitions.json", []),
                values=pd.read_parquet(r / "04_kpi" / "kpi_values.parquet"),
                insights=_json(r / "05_insights" / "insights.json", []),
                quality=qs if qs else _json(FIXTURES / "quality_score.json", {}),
                lineage=_json(r / "audit" / "lineage_graph.json", _json(FIXTURES / "lineage_graph.json", {})),
            )
    return Bundle(
        source="fixtures", run_id=None,
        kpi_defs=_json(FIXTURES / "kpi_definitions.json", []),
        values=_values(FIXTURES / "kpi_values.parquet", FIXTURES / "kpi_values.csv"),
        insights=_json(FIXTURES / "insights.json", []),
        quality=_json(FIXTURES / "quality_score.json", {}),
        lineage=_json(FIXTURES / "lineage_graph.json", {}),
    )
