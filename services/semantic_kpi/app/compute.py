"""KPI computation (mode `compute`). Code computes; no LLM involved.

For every KPI in the catalog (configs/kpis/<domain>.yaml):
  * run its SQL on the warehouse -> one value per month (dimension 'total', value 'all')
  * for each declared dimension, run the SAME SQL with the dimension added to SELECT and GROUP BY
    -> one value per month per dimension value
Each row also carries `n` = number of fact rows behind the value: the analyst uses it to weight ratio KPIs (mix vs
rate decomposition) and to detect incomplete months.

KPI SQL convention (BO5 schema): `SELECT <period expr> AS period, <aggregate> AS value FROM <fact> [WHERE ...] GROUP BY 1`.
The dimension cut is a rewrite of that shape; a KPI that does not follow it is computed for 'total' only, with a warning.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .common import data_dir, event, find_input, load_catalog, load_dataset, stage_dir, write_json

SHAPE = re.compile(r"^\s*SELECT\s+(?P<period>.+?)\s+AS\s+period\s*,\s*(?P<value>.+?)\s+AS\s+value\s+FROM\s+(?P<rest>.+?)\s+GROUP\s+BY\s+1\s*$",
                   re.IGNORECASE | re.DOTALL)


def aggregation_kind(sql: str) -> str:
    """additive (SUM / COUNT: segment values add up to the total) or ratio (averages, rates, divisions)."""
    m = SHAPE.match(sql)
    if not m:
        return "ratio"
    v = m.group("value").strip().upper()
    return "additive" if re.fullmatch(r"(SUM|COUNT)\((?:[^()]|\([^()]*\))*\)", v) else "ratio"


def total_sql(sql: str) -> str:
    """Add n = COUNT(*) to the KPI query (same filters)."""
    m = SHAPE.match(sql)
    if not m:
        return f"SELECT period, value, NULL::BIGINT AS n FROM ({sql})"
    return f"SELECT {m['period']} AS period, {m['value']} AS value, COUNT(*) AS n FROM {m['rest']} GROUP BY 1"


def cut_sql(sql: str, dim: str) -> str | None:
    m = SHAPE.match(sql)
    if not m:
        return None
    return (f"SELECT {m['period']} AS period, COALESCE(CAST({dim} AS VARCHAR), 'unknown') AS dimension_value, "
            f"{m['value']} AS value, COUNT(*) AS n FROM {m['rest']} GROUP BY 1, 2")


def _period_str(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.dt.strftime("%Y-%m")
    return s.astype(str).str.slice(0, 7)


def compute(req: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    cfg = load_dataset(req.config_ref, req.dataset)
    wh = find_input(req.inputs, "warehouse")
    if wh is None or not wh.exists():
        return {"status": "error", "error": {"code": "BAD_INPUT", "message": "missing input 'etl.warehouse' (DuckDB file)"}}
    catalog = load_catalog(cfg)
    out_dir, rel = stage_dir(req.run_id, "04_kpi")
    frames, events, warnings, defs = [], [], [], []

    with duckdb.connect(str(wh), read_only=True) as con:
        for k in catalog:
            kid, sql = k["id"], k["sql"]
            kind = aggregation_kind(sql)
            try:
                df = con.execute(total_sql(sql)).df()
            except duckdb.Error as e:
                warnings.append(f"{kid}: query failed, KPI skipped ({str(e).splitlines()[0][:160]})")
                continue
            df["dimension"], df["dimension_value"] = "total", "all"
            parts = [df]
            # explicit node ids: the KPI node reads the fact table(s) named in its SQL (lineage: fact -> KPI)
            sources = sorted(set(re.findall(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", sql, re.IGNORECASE)) - {"f", "r"})
            events.append(event(req.run_id, "compute_kpi", rule=sql, rows_affected=len(df),
                                inputs=[{"name": t, "node_id": f"dbt.{t}", "path": wh.relative_to(data_dir()).as_posix()} for t in sources],
                                outputs=[{"name": f"kpi.{kid}", "kpi_id": kid, "node_id": f"kpi.{kid}", "rows": len(df)}],
                                params={"kpi_id": kid, "dimension": "total", "aggregation": kind}))
            for dim in k.get("dimensions") or []:
                q = cut_sql(sql, dim)
                if q is None:
                    warnings.append(f"{kid}: SQL does not follow the KPI shape; no cut by {dim}")
                    continue
                try:
                    d = con.execute(q).df()
                except duckdb.Error as e:
                    warnings.append(f"{kid}: cut by {dim} failed ({str(e).splitlines()[0][:160]})")
                    continue
                d["dimension"] = dim
                parts.append(d)
                events.append(event(req.run_id, "compute_kpi_cut", rule=q, rows_affected=len(d),
                                    outputs=[{"name": f"kpi_values[{kid}, {dim}]", "rows": len(d)}],
                                    params={"kpi_id": kid, "dimension": dim}))
            v = pd.concat(parts, ignore_index=True)
            v["kpi_id"] = kid
            frames.append(v)
            defs.append({**{f: k.get(f) for f in ("id", "name", "description", "sql", "grain", "unit", "direction",
                                                   "dimensions", "synonyms", "caveats", "observation_window_months")}, "aggregation": kind})

    if not frames:
        return {"status": "error", "error": {"code": "INTERNAL", "message": "no KPI could be computed"}, "warnings": warnings}
    values = pd.concat(frames, ignore_index=True)
    values = values[values["period"].notna()].copy()
    values["period"] = _period_str(values["period"])
    values["value"] = pd.to_numeric(values["value"], errors="coerce").astype("float64")
    values["n"] = pd.to_numeric(values["n"], errors="coerce").astype("Int64")
    values = values[["kpi_id", "period", "dimension", "dimension_value", "value", "n"]].sort_values(
        ["kpi_id", "dimension", "dimension_value", "period"]).reset_index(drop=True)
    values.to_parquet(out_dir / "kpi_values.parquet", index=False)
    write_json(out_dir / "kpi_definitions.json", defs)

    return {
        "status": "partial" if warnings else "ok",
        "outputs": [
            {"name": "kpi_values", "kind": "parquet", "path": f"{rel}/kpi_values.parquet", "rows": len(values)},
            {"name": "kpi_definitions", "kind": "json", "path": f"{rel}/kpi_definitions.json"},
        ],
        "metrics": {"kpis": len(defs), "rows": len(values), "periods": int(values["period"].nunique()),
                    "dimension_cuts": int(values.loc[values.dimension != "total", ["kpi_id", "dimension"]].drop_duplicates().shape[0]),
                    "seconds": round(time.perf_counter() - t0, 2)},
        "warnings": warnings,
        "lineage_events": events,
    }
