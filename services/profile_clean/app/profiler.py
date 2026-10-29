"""Deterministic table/column profiling."""
from __future__ import annotations

from typing import Any

import pandas as pd

from .lineage import LineageTracker


def _col_profile(series: pd.Series) -> dict[str, Any]:
    n = len(series)
    nulls = int(series.isna().sum())
    prof: dict[str, Any] = {
        "dtype": str(series.dtype),
        "null_count": nulls,
        "null_pct": round(100.0 * nulls / n, 4) if n else 0.0,
        "distinct_count": int(series.nunique(dropna=True)),
    }
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        s = series.dropna()
        if len(s):
            prof.update(
                {
                    "min": float(s.min()),
                    "max": float(s.max()),
                    "mean": float(s.mean()),
                    "std": float(s.std()) if len(s) > 1 else 0.0,
                    "iqr_outliers": int(_iqr_outlier_count(s)),
                }
            )
    else:
        vc = series.astype(str).value_counts().head(5)
        prof["top_values"] = {str(k): int(v) for k, v in vc.items()}
        prof["pattern_checks"] = _pattern_checks(series)
    return prof


def _iqr_outlier_count(s: pd.Series) -> int:
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return 0
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return int(((s < lo) | (s > hi)).sum())


def _pattern_checks(series: pd.Series) -> dict[str, Any]:
    s = series.dropna().astype(str)
    if s.empty:
        return {}
    checks: dict[str, Any] = {}
    sample = s.head(200)
    date_like = sample.str.match(r"^\d{4}-\d{2}-\d{2}").mean()
    if date_like > 0.5:
        parsed = pd.to_datetime(sample, errors="coerce")
        checks["date_parseable_pct"] = round(100 * parsed.notna().mean(), 2)
    zip_like = sample.str.match(r"^\d{5}(-\d{3})?$").mean()
    if zip_like > 0.3:
        checks["zip_like_pct"] = round(100 * zip_like, 2)
    id_like = sample.str.match(r"^[a-f0-9]{32}$|^[A-Z0-9-]{8,}$").mean()
    if id_like > 0.3:
        checks["id_like_pct"] = round(100 * id_like, 2)
    return checks


def _table_profile(df: pd.DataFrame, pk_cols: list[str] | None) -> dict[str, Any]:
    dup_rows = int(df.duplicated().sum())
    prof: dict[str, Any] = {
        "rows": len(df),
        "duplicate_rows": dup_rows,
        "columns": {c: _col_profile(df[c]) for c in df.columns},
    }
    if pk_cols:
        present = [c for c in pk_cols if c in df.columns]
        if present:
            prof["duplicate_keys"] = int(df.duplicated(subset=present).sum())
    return prof


def _fk_orphans(tables: dict[str, pd.DataFrame], relationships: list[dict[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rel in relationships:
        fr = rel.get("from", "")
        to = rel.get("to", "")
        if "." not in fr or "." not in to:
            continue
        ft, fc = fr.split(".", 1)
        tt, tc = to.split(".", 1)
        if ft not in tables or tt not in tables:
            continue
        if fc not in tables[ft].columns or tc not in tables[tt].columns:
            continue
        left = tables[ft][fc].dropna()
        right = set(tables[tt][tc].dropna().unique())
        orphans = int((~left.isin(right)).sum())
        rate = round(100.0 * orphans / len(left), 4) if len(left) else 0.0
        key = f"{fr}->{to}"
        out[key] = {"orphan_count": orphans, "orphan_rate_pct": rate}
    return out


def profile_dataset(
    tables: dict[str, pd.DataFrame],
    relationships: list[dict[str, str]],
    pk_map: dict[str, list[str]] | None,
    lineage: LineageTracker,
) -> dict[str, Any]:
    table_profiles = {}
    for name, df in tables.items():
        table_profiles[name] = _table_profile(df, (pk_map or {}).get(name))
    result = {
        "tables": table_profiles,
        "relationships": _fk_orphans(tables, relationships),
    }
    lineage.emit("profile_tables", rule="pandas_profile", rows_affected=sum(len(d) for d in tables.values()))
    return result


def profile_diff(before: dict[str, Any], after: dict[str, Any], lang: str = "en") -> tuple[dict[str, Any], str]:
    diff: dict[str, Any] = {"tables": {}}
    lines = ["# Profile diff (before → after)\n"]
    if lang == "fr":
        lines[0] = "# Diff de profil (avant → après)\n"
    all_tables = set(before.get("tables", {})) | set(after.get("tables", {}))
    for t in sorted(all_tables):
        b = before.get("tables", {}).get(t, {})
        a = after.get("tables", {}).get(t, {})
        tdiff: dict[str, Any] = {
            "rows_before": b.get("rows"),
            "rows_after": a.get("rows"),
            "duplicate_rows_before": b.get("duplicate_rows"),
            "duplicate_rows_after": a.get("duplicate_rows"),
            "columns": {},
        }
        cols = set(b.get("columns", {})) | set(a.get("columns", {}))
        for c in sorted(cols):
            bc = b.get("columns", {}).get(c, {})
            ac = a.get("columns", {}).get(c, {})
            tdiff["columns"][c] = {
                "null_pct_before": bc.get("null_pct"),
                "null_pct_after": ac.get("null_pct"),
                "iqr_outliers_before": bc.get("iqr_outliers"),
                "iqr_outliers_after": ac.get("iqr_outliers"),
            }
        diff["tables"][t] = tdiff
        lines.append(f"## {t}\n")
        lines.append(f"- rows: {tdiff['rows_before']} → {tdiff['rows_after']}\n")
        lines.append(f"- duplicate rows: {tdiff['duplicate_rows_before']} → {tdiff['duplicate_rows_after']}\n")
    return diff, "".join(lines)


def optional_html_report(tables: dict[str, pd.DataFrame], out_path: str) -> bool:
    try:
        from ydata_profiling import ProfileReport  # type: ignore[import-untyped]

        combined = pd.concat(
            [df.assign(_table=name) for name, df in list(tables.items())[:3]],
            ignore_index=True,
        )
        ProfileReport(combined, minimal=True, title="BIFlow profile").to_file(out_path)
        return True
    except Exception:
        return False
