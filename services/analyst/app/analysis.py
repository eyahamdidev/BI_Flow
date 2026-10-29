"""Analysis maths (BO6). Pure functions on the KPI table: no I/O, no LLM. Each one is unit-tested.

kpi_values columns: kpi_id, period ('YYYY-MM'), dimension ('total' or a column), dimension_value ('all' for total),
value, n (number of fact rows behind the value).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

MIN_SHARE_OF_MEDIAN = 0.10   # a month with < 10% of the KPI's usual row count is incomplete (start/end of the data)
Z_REVIEW, Z_HIGH = 3.0, 4.0  # robust z thresholds
TREND_WINDOW = 12            # months used for the trend
P_SIGNIFICANT = 0.05


def complete_periods(total: pd.DataFrame) -> list[str]:
    """Months with enough rows to be trusted, in order. `total` = one KPI's total rows."""
    t = total.sort_values("period")
    if t["n"].isna().all():
        return list(t["period"])
    med = float(t["n"].median())
    return list(t.loc[t["n"].fillna(0) >= MIN_SHARE_OF_MEDIAN * med, "period"])


def trend(series: pd.Series) -> dict[str, Any] | None:
    """Linear slope over the last TREND_WINDOW complete months. series: value indexed by period (sorted)."""
    s = series.dropna().iloc[-TREND_WINDOW:]
    if len(s) < 6:
        return None
    x = np.arange(len(s))
    if float(np.ptp(s.values)) == 0.0:  # perfectly flat series: no slope, and linregress would return p = NaN
        v = round(float(s.iloc[0]), 4)
        return {"direction": "flat", "slope_per_month": 0.0, "p_value": 1.0, "relative_slope_pct": 0.0,
                "window_start": s.index[0], "window_end": s.index[-1], "first_value": v, "last_value": v, "months": len(s)}
    fit = stats.linregress(x, s.values)
    mean = float(np.mean(np.abs(s.values))) or 1.0
    pvalue = float(fit.pvalue) if np.isfinite(fit.pvalue) else 1.0  # never write NaN (not valid JSON)
    direction = "flat" if pvalue >= P_SIGNIFICANT else ("up" if fit.slope > 0 else "down")
    return {"direction": direction, "slope_per_month": round(float(fit.slope), 6), "p_value": round(pvalue, 4),
            "relative_slope_pct": round(100 * float(fit.slope) / mean, 2), "window_start": s.index[0], "window_end": s.index[-1],
            "first_value": round(float(s.iloc[0]), 4), "last_value": round(float(s.iloc[-1]), 4), "months": len(s)}


def anomalies(series: pd.Series) -> list[dict[str, Any]]:
    """Robust z-score (median/MAD) on the residuals of a linear fit: steady growth is not an anomaly."""
    s = series.dropna()
    if len(s) < 8:
        return []
    x = np.arange(len(s))
    fit = stats.linregress(x, s.values)
    expected = fit.intercept + fit.slope * x
    resid = s.values - expected
    mad = float(np.median(np.abs(resid - np.median(resid))))
    scale = 1.4826 * mad if mad > 0 else (float(np.std(resid)) or 1.0)
    out = []
    for i, (period, actual) in enumerate(s.items()):
        z = (resid[i] - np.median(resid)) / scale
        if abs(z) >= Z_REVIEW:
            out.append({"period": period, "actual": round(float(actual), 4), "expected": round(float(expected[i]), 4),
                        "z": round(float(z), 2), "direction": "high" if z > 0 else "low",
                        "severity": "high" if abs(z) >= Z_HIGH else "review"})
    return out


def decompose(cut: pd.DataFrame, period: str, prev: str, additive: bool, total_t: float, total_prev: float) -> dict[str, Any]:
    """Split total_t - total_prev across the dimension values of `cut` (one dimension, both periods).

    additive (SUM/COUNT): contribution_i = v_i,t - v_i,prev.
    ratio (averages/rates): total = sum_i w_i * r_i with w_i = n_i / N, so
        contribution_i = w_i,t * r_i,t - w_i,prev * r_i,prev
        = mix_i  (w_i,t - w_i,prev) * (r_i,t + r_i,prev) / 2      the segment's SHARE changed
        + rate_i (r_i,t - r_i,prev) * (w_i,t + w_i,prev) / 2      the segment's own VALUE changed
    Whatever the segments cannot explain (e.g. AVG skipping NULLs) is returned as an explicit 'unexplained' row,
    so the contributions always sum to the total delta.
    """
    a = cut[cut.period == period].set_index("dimension_value")
    b = cut[cut.period == prev].set_index("dimension_value")
    keys = a.index.union(b.index)
    rows = []
    for k in keys:
        vt = float(a["value"].get(k, np.nan)) if k in a.index else np.nan
        vp = float(b["value"].get(k, np.nan)) if k in b.index else np.nan
        if additive:
            d = (0.0 if np.isnan(vt) else vt) - (0.0 if np.isnan(vp) else vp)
            rows.append({"dimension_value": str(k), "delta": d, "value_t": None if np.isnan(vt) else vt,
                         "value_prev": None if np.isnan(vp) else vp})
        else:
            nt = float(a["n"].get(k, 0) or 0) if k in a.index else 0.0
            np_ = float(b["n"].get(k, 0) or 0) if k in b.index else 0.0
            wt = nt / float(a["n"].sum() or 1)
            wp = np_ / float(b["n"].sum() or 1)
            rt = 0.0 if np.isnan(vt) else vt
            rp = 0.0 if np.isnan(vp) else vp
            mix = (wt - wp) * (rt + rp) / 2
            rate = (rt - rp) * (wt + wp) / 2
            rows.append({"dimension_value": str(k), "delta": mix + rate, "mix": mix, "rate": rate,
                         "value_t": None if np.isnan(vt) else vt, "value_prev": None if np.isnan(vp) else vp,
                         "share_t": wt, "share_prev": wp})
    # round FIRST, then put whatever the rounded parts do not explain in an explicit row: the sum is exact by construction
    for r in rows:
        for f in ("delta", "mix", "rate", "value_t", "value_prev", "share_t", "share_prev"):
            if r.get(f) is not None:
                r[f] = round(float(r[f]), 6)
    total_delta = round(total_t - total_prev, 6)
    resid = round(total_delta - sum(r["delta"] for r in rows), 6)
    if resid != 0:
        rows.append({"dimension_value": "(unexplained)", "delta": resid})
    rows.sort(key=lambda r: -abs(r["delta"]))
    return {"period": period, "compare_to": prev, "total_delta": total_delta, "value_t": round(total_t, 6),
            "value_prev": round(total_prev, 6), "contributions": rows}


def concentration(dec: dict[str, Any]) -> float:
    """Share of |total delta| carried by the top contribution: picks the most telling dimension."""
    tot = sum(abs(c["delta"]) for c in dec["contributions"]) or 1.0
    top = next((c for c in dec["contributions"] if c["dimension_value"] != "(unexplained)"), None)
    return abs(top["delta"]) / tot if top else 0.0


def correlation(a: pd.Series, b: pd.Series) -> float | None:
    j = pd.concat([a, b], axis=1).dropna()
    if len(j) < 6 or j.iloc[:, 0].std() == 0 or j.iloc[:, 1].std() == 0:
        return None
    return round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 3)
