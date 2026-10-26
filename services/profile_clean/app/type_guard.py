"""Type-safety guard: block unsafe cleaning actions regardless of YAML."""
from __future__ import annotations

from typing import Any

import pandas as pd

from .column_roles import (
    ColumnRoleInfo,
    role_allows_mode_impute,
    role_allows_numeric_impute,
    role_allows_outliers,
)
from .lineage import LineageTracker

FORBIDDEN_IMPUTE_ROLES = frozenset({"id", "categorical", "binary_flag", "free_text", "datetime", "constant", "all_null"})


def snapshot_dtypes(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, str]]:
    return {t: {c: str(df[c].dtype) for c in df.columns} for t, df in tables.items()}


def _norm_dtype(d: str) -> str:
    return d.replace("numpy.", "").replace("pandas.", "")


def dtypes_compatible(before: str, after: str) -> bool:
    b, a = _norm_dtype(before), _norm_dtype(after)
    if b == a:
        return True
    pairs = {
        ("int64", "Int64"),
        ("float64", "Float64"),
        ("bool", "boolean"),
        ("object", "string"),
        ("str", "string"),
        ("string", "str"),
    }
    return (b, a) in pairs or (a, b) in pairs


def block_action(
    state: Any,
    lineage: LineageTracker,
    *,
    table: str,
    column: str,
    action: str,
    reason: str,
) -> None:
    msg = f"type-safety guard: {reason}"
    state.review_queue.append(
        {
            "table": table,
            "column": column,
            "issue": action,
            "suggested_action": "skip",
            "reason": msg,
            "source": "type_guard",
        }
    )
    state.warnings.append(msg)
    lineage.emit("type_guard_block", rule=f"type_guard_block: {action} on {table}.{column} — {reason}")


def guard_numeric_impute(
    role: ColumnRoleInfo,
    table: str,
    col: str,
    series: pd.Series,
    state: Any,
    lineage: LineageTracker,
) -> bool:
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        block_action(state, lineage, table=table, column=col, action="median_impute", reason="string column")
        return False
    if role.role in FORBIDDEN_IMPUTE_ROLES:
        block_action(state, lineage, table=table, column=col, action="median_impute", reason=f"role={role.role}")
        return False
    if not role_allows_numeric_impute(role.role):
        block_action(state, lineage, table=table, column=col, action="median_impute", reason=f"role={role.role}")
        return False
    return True


def guard_mode_impute(
    role: ColumnRoleInfo,
    table: str,
    col: str,
    state: Any,
    lineage: LineageTracker,
) -> bool:
    if not role_allows_mode_impute(role.role) and role.role not in ("categorical",):
        block_action(state, lineage, table=table, column=col, action="mode_impute", reason=f"role={role.role}")
        return False
    return True


def guard_outlier(
    role: ColumnRoleInfo,
    table: str,
    col: str,
    series: pd.Series,
    state: Any,
    lineage: LineageTracker,
    *,
    discrete_outliers: bool = False,
) -> bool:
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        block_action(state, lineage, table=table, column=col, action="outlier_flag", reason="string column")
        return False
    if role.role in ("id", "binary_flag", "categorical", "free_text", "datetime"):
        block_action(state, lineage, table=table, column=col, action="outlier_flag", reason=f"role={role.role}")
        return False
    if not role_allows_outliers(role.role, discrete_outliers=discrete_outliers):
        block_action(state, lineage, table=table, column=col, action="outlier_flag", reason=f"role={role.role}")
        return False
    return True


def restore_column_dtype(series: pd.Series, original_dtype: str, *, is_integer: bool = False) -> pd.Series:
    if is_integer or "int" in original_dtype.lower():
        return pd.to_numeric(series, errors="coerce").round().astype("Int64")
    if "float" in original_dtype.lower():
        return pd.to_numeric(series, errors="coerce")
    if "bool" in original_dtype.lower():
        return series
    return series.astype("string")


def sanitize_string_nulls(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_string_dtype(out[c]) or out[c].dtype == object:
            s = out[c].astype("string")
            out[c] = s.replace({"nan": pd.NA, "NaN": pd.NA, "None": pd.NA, "<NA>": pd.NA})
    return out
