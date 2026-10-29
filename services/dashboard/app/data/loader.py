"""Data layer: reads a run's outputs from DATA_DIR/runs/<run_id>/ (read-only), or the bundled fixtures (demo mode).

Everything is found through the run manifest's artifact map, so the dashboard does not hard-code stage folders.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@dataclass
class Bundle:
    source: str                      # "fixtures" or "run"
    run_id: str | None
    kpi_defs: list[dict]
    values: pd.DataFrame             # kpi_id, period, dimension, dimension_value, value[, n]
    insights: list[dict]
    quality: dict                    # {"before": {...metrics}, "after": {...metrics}, "tables_before": {...}, ...}
    lineage: dict                    # {"nodes": [...], "edges": [...]}
    config: dict = field(default_factory=dict)       # dashboard_config.json
    drivers: dict = field(default_factory=dict)      # drivers.json
    manifest: dict = field(default_factory=dict)
    trace_md: str = ""
    profile_diff_md: str = ""


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def list_runs() -> list[str]:
    d = data_dir() / "runs"
    if not d.exists():
        return []
    return sorted((p.name for p in d.iterdir() if p.is_dir() and (p / "run_manifest.json").exists()), reverse=True)


def runs_with_kpis() -> list[str]:
    return [r for r in list_runs() if _artifact(_manifest(r), "kpi_values")]


def _json(p: Path | None, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else default
    except (OSError, ValueError):
        return default


def _manifest(run_id: str) -> dict:
    return _json(data_dir() / "runs" / run_id / "run_manifest.json", {})


def _artifact(m: dict, name: str, stage: str | None = None) -> Path | None:
    for key, rel in (m.get("artifacts") or {}).items():
        st, _, art = key.partition(".")
        if art == name and (stage is None or st == stage):
            p = data_dir() / rel
            return p if p.exists() else None
    return None


def _text(p: Path | None) -> str:
    return p.read_text(encoding="utf-8") if p and p.exists() else ""


def load(run_id: str | None = None) -> Bundle:
    if run_id:
        m = _manifest(run_id)
        vp = _artifact(m, "kpi_values")
        if vp:
            qb = _json(_artifact(m, "quality_score", "score_before"), {})
            qa = _json(_artifact(m, "quality_score", "score_after"), {})
            quality = {"before": qb.get("metrics", {}), "after": qa.get("metrics", {}),
                       "tables_before": qb.get("tables", {}), "tables_after": qa.get("tables", {})} if qb and qa else {}
            return Bundle(
                source="run", run_id=run_id,
                kpi_defs=_json(_artifact(m, "kpi_definitions"), []),
                values=pd.read_parquet(vp),
                insights=_json(_artifact(m, "insights"), []),
                quality=quality,
                lineage=_json(_artifact(m, "lineage_graph"), {}),
                config=_json(_artifact(m, "dashboard_config"), {}),
                drivers=_json(_artifact(m, "drivers"), {}),
                manifest=m,
                trace_md=_text(_artifact(m, "trace_report_md") or _artifact(m, "trace_report")),
                profile_diff_md=_text(_artifact(m, "profile_diff_md")),
            )
    values = pd.read_csv(FIXTURES / "kpi_values.csv")
    return Bundle(
        source="fixtures", run_id=None,
        kpi_defs=_json(FIXTURES / "kpi_definitions.json", []),
        values=values,
        insights=_json(FIXTURES / "insights.json", []),
        quality=_json(FIXTURES / "quality_score.json", {}),
        lineage=_json(FIXTURES / "lineage_graph.json", {}),
    )


STATUS_WORD = {"ok": "ok", "failed": "failed", "running": "running"}


def run_label(run_id: str) -> str:
    """'olist · 29 Oct 2026 19:44 · ok' instead of the raw id (the id stays visible at the end)."""
    m = _manifest(run_id)
    try:
        when = f"{run_id[6:8]}/{run_id[4:6]}/{run_id[0:4]} {run_id[9:11]}:{run_id[11:13]}"
    except IndexError:
        when = ""
    status = m.get("status", "?")
    if status == "running":  # no stage written for 30 min: the run was stopped, it will not finish
        import time

        mf = data_dir() / "runs" / run_id / "run_manifest.json"
        if mf.exists() and time.time() - mf.stat().st_mtime > 1800:
            status = "interrupted"
    return f"{m.get('dataset', '?')} · {when} · {STATUS_WORD.get(status, status)}  ({run_id[-4:]})"
