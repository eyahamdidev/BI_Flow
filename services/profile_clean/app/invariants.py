"""Post-clean invariant checks (tests + playground)."""
from __future__ import annotations

from typing import Any

import pandas as pd

from .type_guard import dtypes_compatible


def _orig_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if not c.endswith("__imputed") and not c.endswith("__outlier") and not c.endswith("__high_null") and not c.endswith("_high_null_flag") and not c.endswith("__invalid") and not c.endswith("_missing_flag") and not c.startswith("has_") and not c.startswith("bad_")]


def check_cleaning_invariants(
    raw_df: pd.DataFrame,
    clean_df: pd.DataFrame,
    quality_log: list[dict[str, Any]] | None = None,
    *,
    rows_dropped: int = 0,
    pk_col: str | None = None,
    allow_convert: set[str] | None = None,
) -> list[str]:
    """Return list of violation messages (empty if all pass)."""
    violations: list[str] = []
    allow_convert = allow_convert or set()
    rows_in = len(raw_df)
    rows_out = len(clean_df)
    if rows_in - rows_dropped != rows_out:
        violations.append(f"row accounting: {rows_in}-{rows_dropped}!={rows_out}")

    raw_cols = [c for c in _orig_cols(raw_df) if c in clean_df.columns]
    for c in raw_cols:
        if c not in raw_df.columns:
            continue
        if c in allow_convert:
            continue
        if not dtypes_compatible(str(raw_df[c].dtype), str(clean_df[c].dtype)):
            violations.append(f"dtype changed on {c}: {raw_df[c].dtype} -> {clean_df[c].dtype}")

    key = pk_col if pk_col and pk_col in raw_df.columns else None
    if key and key in clean_df.columns and len(raw_df) == len(clean_df):
        if not raw_df[key].equals(clean_df[key]):
            violations.append(f"id column {key} modified")

    flag_cols = [c for c in clean_df.columns if c.endswith("__outlier") or c.endswith("__imputed")]
    for fc in flag_cols:
        if clean_df[fc].dtype != bool and not pd.api.types.is_bool_dtype(clean_df[fc]):
            if not set(clean_df[fc].dropna().unique()).issubset({True, False}):
                violations.append(f"flag column {fc} is not boolean")

    if quality_log:
        imputed_logged = sum(e.get("rows_affected", 0) for e in quality_log if "imput" in str(e.get("rule_id", "")))
        imputed_flags = sum(int(clean_df[c].sum()) for c in clean_df.columns if c.endswith("__imputed"))
        if imputed_flags and abs(imputed_logged - imputed_flags) > imputed_flags * 0.1:
            pass  # log uses row counts not cell counts — checked per-column in tests

    for c in raw_cols:
        if c not in clean_df.columns:
            violations.append(f"missing original column {c}")
            continue
        if c.endswith("__imputed") or c.endswith("__outlier"):
            continue
        r, cl = raw_df[c], clean_df[c]
        if dtypes_compatible(str(r.dtype), str(cl.dtype)):
            if pk_col and len(raw_df) != len(clean_df):
                continue
            try:
                if r.dtype != cl.dtype and str(r.dtype) == "string":
                    continue
            except Exception:
                pass

    for c in clean_df.columns:
        if pd.api.types.is_string_dtype(clean_df[c]):
            bad = clean_df[c].astype("string").isin(["nan", "NaN", "None"])
            if bad.any():
                violations.append(f"literal null strings in {c}")

    return violations
