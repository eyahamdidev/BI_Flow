"""Dashboard generator (mode `dashboard_config`): kpi_definitions + kpi_values + insights -> dashboard_config.json.

Config only, no dataset-specific code: one tile per KPI (latest COMPLETE month, delta vs the previous one, 12-month
sparkline), one trend chart per KPI with its anomaly months, one breakdown chart per declared dimension.
The Streamlit app renders whatever this file describes, so a new dataset gets a dashboard with no code change.
"""
from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd

from . import analysis as A
from .insights import _event, data_dir, find_input


def dashboard_config(req: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    vp, dp, ip, rp = (find_input(req.inputs, n) for n in ("kpi_values", "kpi_definitions", "insights", "drivers"))
    if not vp or not vp.exists() or not dp or not dp.exists():
        return {"status": "error", "error": {"code": "BAD_INPUT", "message": "missing inputs kpi_values / kpi_definitions"}}
    values = pd.read_parquet(vp)
    defs = json.loads(dp.read_text(encoding="utf-8"))
    insights = json.loads(ip.read_text(encoding="utf-8")) if ip and ip.exists() else []
    # same complete months as the analysis (analyst writes them in drivers.json), so tiles and insights agree
    incomplete = (json.loads(rp.read_text(encoding="utf-8")).get("incomplete_periods") or {}) if rp and rp.exists() else {}

    tiles, charts = [], []
    for d in defs:
        kv = values[values.kpi_id == d["id"]]
        total = kv[kv.dimension == "total"]
        if d["id"] in incomplete:
            good = sorted(set(total.period) - set(incomplete[d["id"]]))
        else:
            good = A.complete_periods(total)
        s = total.set_index("period")["value"].reindex(good).dropna()
        if s.empty:
            continue
        cur, prev = float(s.iloc[-1]), (float(s.iloc[-2]) if len(s) > 1 else None)
        tiles.append({"kpi_id": d["id"], "name": d["name"], "unit": d.get("unit"), "direction": d.get("direction"),
                      "period": s.index[-1], "value": cur, "previous": prev,
                      "delta_pct": round(100 * (cur - prev) / abs(prev), 2) if prev else None,
                      "sparkline": [{"period": p, "value": float(v)} for p, v in s.iloc[-12:].items()],
                      "insight_count": sum(1 for i in insights if i["kpi_id"] == d["id"])})
        charts.append({"type": "trend", "kpi_id": d["id"], "title": d["name"], "unit": d.get("unit"),
                       "complete_periods": good, "incomplete_periods": sorted(set(total.period) - set(good)),
                       "anomaly_periods": [i["period"] for i in insights if i["kpi_id"] == d["id"] and i["type"] == "anomaly"]})
        for dim in d.get("dimensions") or []:
            if (kv.dimension == dim).any():
                charts.append({"type": "breakdown", "kpi_id": d["id"], "dimension": dim, "title": f"{d['name']} by {dim}",
                               "unit": d.get("unit"), "period": s.index[-1], "top_n": 10})
    cfg = {"title": f"BIFlow · {req.dataset}", "run_id": req.run_id, "source_label": f"run {req.run_id} · dataset {req.dataset}",
           "tiles": tiles, "charts": charts,
           "dimensions": sorted({c["dimension"] for c in charts if c["type"] == "breakdown"}),
           "periods": sorted(values.period.unique().tolist())}
    out = data_dir() / "runs" / req.run_id / "06_dashboard"
    out.mkdir(parents=True, exist_ok=True)
    (out / "dashboard_config.json").write_text(json.dumps(cfg, indent=2, default=str), encoding="utf-8")
    rel = f"runs/{req.run_id}/06_dashboard/dashboard_config.json"
    return {"status": "ok", "outputs": [{"name": "dashboard_config", "kind": "json", "path": rel}],
            "metrics": {"tiles": len(tiles), "charts": len(charts), "seconds": round(time.perf_counter() - t0, 2)},
            "lineage_events": [_event(req.run_id, "dashboard_config", rule="kpi_definitions + insights -> tiles/charts",
                                      rows_affected=len(tiles))]}
