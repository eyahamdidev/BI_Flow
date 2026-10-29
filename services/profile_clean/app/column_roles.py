"""Deterministic column role inference for profile_clean (service + playground).

Roles: id, categorical, binary_flag, discrete_count, continuous_numeric, datetime,
free_text, constant, all_null.

Thresholds can be overridden via YAML ``cleaning_rules.role_inference``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

ID_NAME_RE = re.compile(r"(^|_)(id|key|uuid|code|number|no)($|_)", re.I)
COUNT_NAME_RE = re.compile(r"(count|qty|quantity|num|number of|sibsp|parch)", re.I)
NUMERIC_PARSE_MIN = 0.98
UNIQUE_ID_RATIO = 0.95
FREE_TEXT_UNIQ = 0.85
FREE_TEXT_MIN_LEN = 40

ROLES = frozenset(
    {
        "id",
        "categorical",
        "binary_flag",
        "discrete_count",
        "continuous_numeric",
        "datetime",
        "free_text",
        "constant",
        "all_null",
    }
)


@dataclass(frozen=True)
class ColumnRoleInfo:
    role: str
    why: str
    storage_dtype: str  # str | int | float | bool | datetime


def _default_cfg() -> dict[str, Any]:
    return {
        "numeric_parse_min": NUMERIC_PARSE_MIN,
        "unique_id_ratio": UNIQUE_ID_RATIO,
        "categorical_max_cardinality": None,
        "categorical_max_distinct_int": 10,
        "high_null_pct": 60.0,
        "free_text_uniq_ratio": FREE_TEXT_UNIQ,
    }


def _series_as_str(s: pd.Series) -> pd.Series:
    return s.astype("string")


def _distinct(s: pd.Series) -> pd.Series:
    """Distinct non-null values: same answer as the full column for any()/set questions, far cheaper on 1M rows."""
    return pd.Series(s.dropna().unique())


def _has_letter_token(s: pd.Series) -> bool:
    ss = _series_as_str(_distinct(s)).dropna()
    if ss.empty:
        return False
    return ss.str.contains(r"[A-Za-z]", regex=True).any()


def _strict_numeric_fraction(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) > 200_000:  # a proportion: a fixed 200k-row sample gives the same answer to within rounding
        s = s.sample(200_000, random_state=0)
    ss = _series_as_str(s).dropna()
    if ss.empty:
        return 0.0
    parsed = pd.to_numeric(ss, errors="coerce")
    return float(parsed.notna().mean())


def _is_binary_values(s: pd.Series) -> bool:
    ss = _series_as_str(_distinct(s)).dropna()
    if ss.empty:
        return False
    uniq = set(ss.str.lower().unique())
    if len(uniq) != 2:
        return False
    allowed = {"0", "1", "true", "false", "yes", "no", "y", "n", "t", "f", "m"}
    return uniq.issubset(allowed) or uniq.issubset({"0", "1"})


def infer_column_role(
    col: str,
    series: pd.Series,
    *,
    role_cfg: dict[str, Any] | None = None,
    n_rows: int | None = None,
) -> ColumnRoleInfo:
    cfg = {**_default_cfg(), **(role_cfg or {})}
    n_rows = n_rows or len(series)
    s = series
    non_null = s.dropna()
    if non_null.empty:
        return ColumnRoleInfo("all_null", "all values missing", "str")

    n_unique = int(non_null.nunique())
    if n_unique == 1:
        return ColumnRoleInfo("constant", "constant: 1 value", _storage_dtype(series))

    if pd.api.types.is_datetime64_any_dtype(s):
        return ColumnRoleInfo("datetime", "datetime values", "datetime")

    cl = col.lower()
    uniq_ratio = n_unique / max(len(non_null), 1)

    if ID_NAME_RE.search(cl):
        return ColumnRoleInfo("id", f"name matches id-like pattern ({cl})", "str")

    if _has_letter_token(non_null):
        if uniq_ratio >= cfg["unique_id_ratio"] or "ticket" in cl or "name" in cl:
            return ColumnRoleInfo("id", "alphanumeric labels with letters", "str")
        if n_unique <= _cat_max(cfg, n_rows):
            return ColumnRoleInfo("categorical", f"categorical, {n_unique} values", "str")
        if uniq_ratio >= cfg["free_text_uniq_ratio"]:
            avg_len = _series_as_str(non_null).str.len().mean()
            if avg_len and avg_len >= FREE_TEXT_MIN_LEN:
                return ColumnRoleInfo("free_text", "high-cardinality text", "str")
        return ColumnRoleInfo("categorical", f"mixed text, {n_unique} values", "str")

    num_frac = _strict_numeric_fraction(non_null)
    if num_frac < cfg["numeric_parse_min"]:
        if n_unique <= _cat_max(cfg, n_rows):
            return ColumnRoleInfo("categorical", f"categorical, {n_unique} values", "str")
        return ColumnRoleInfo(
            "free_text" if uniq_ratio >= 0.5 else "categorical",
            f"mixed-type column ({num_frac:.0%} parse as numeric)",
            "str",
        )

    if _is_binary_values(non_null):
        if set(_series_as_str(non_null).str.lower().unique()).issubset({"0", "1"}):
            return ColumnRoleInfo("binary_flag", "binary 0/1", "int")
        return ColumnRoleInfo("binary_flag", "binary categorical pair", "str")

    parsed = pd.to_numeric(_series_as_str(s), errors="coerce")
    int_like = parsed.dropna().apply(lambda x: float(x).is_integer()).all() if parsed.notna().any() else False
    n_distinct = int(parsed.nunique())

    if n_distinct <= cfg["categorical_max_distinct_int"] and int_like:
        return ColumnRoleInfo("categorical", f"categorical, {n_distinct} values", "int")

    if int_like and uniq_ratio >= cfg["unique_id_ratio"]:
        return ColumnRoleInfo("id", f"near-unique integers ({n_unique} unique)", "int")

    if int_like and (parsed >= 0).all() and (COUNT_NAME_RE.search(cl) or n_distinct <= 30):
        return ColumnRoleInfo("discrete_count", f"non-negative integer counts ({n_distinct} distinct)", "int")

    return ColumnRoleInfo(
        "continuous_numeric",
        f"continuous numeric ({n_distinct} distinct)",
        "float" if not int_like else "float",
    )


def _cat_max(cfg: dict[str, Any], n_rows: int) -> int:
    explicit = cfg.get("categorical_max_cardinality")
    if explicit is not None:
        return int(explicit)
    return max(20, int(0.05 * n_rows))


def _storage_dtype(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_integer_dtype(series):
        return "int"
    if pd.api.types.is_float_dtype(series):
        return "float"
    return "str"


def infer_table_roles(
    df: pd.DataFrame,
    role_cfg: dict[str, Any] | None = None,
) -> dict[str, ColumnRoleInfo]:
    return {c: infer_column_role(c, df[c], role_cfg=role_cfg, n_rows=len(df)) for c in df.columns}


def roles_from_config(ds_cfg: dict[str, Any], tables: dict[str, pd.DataFrame]) -> dict[str, ColumnRoleInfo]:
    """YAML ``expected_schema`` role fields with fallback inference."""
    role_cfg = ds_cfg.get("cleaning_rules", {}).get("role_inference", {})
    out: dict[str, ColumnRoleInfo] = {}
    schema = ds_cfg.get("expected_schema", {})
    for t, df in tables.items():
        t_schema = schema.get(t, {})
        for c in df.columns:
            key = f"{t}.{c}"
            spec = t_schema.get(c)
            if isinstance(spec, dict) and spec.get("role") in ROLES:
                why = str(spec.get("why", "from YAML"))
                dtype = str(spec.get("dtype", spec.get("type", _storage_dtype(df[c]))))
                out[key] = ColumnRoleInfo(str(spec["role"]), why, dtype)
            else:
                out[key] = infer_column_role(c, df[c], role_cfg=role_cfg, n_rows=len(df))
    return out


def role_allows_numeric_impute(role: str) -> bool:
    return role in ("continuous_numeric", "discrete_count")


def role_allows_mode_impute(role: str) -> bool:
    return role == "categorical"


def role_allows_outliers(role: str, *, discrete_outliers: bool = False) -> bool:
    if role == "continuous_numeric":
        return True
    if role == "discrete_count" and discrete_outliers:
        return True
    return False


def apply_role_dtypes(df: pd.DataFrame, roles: dict[str, ColumnRoleInfo]) -> pd.DataFrame:
    """Coerce ingest dtypes conservatively from inferred roles."""
    out = df.copy()
    for c, info in roles.items():
        if c not in out.columns:
            continue
        s = out[c]
        if info.role == "all_null":
            out[c] = pd.Series([pd.NA] * len(out), dtype="string")
            continue
        if info.role in ("id", "categorical", "free_text", "binary_flag") and info.storage_dtype == "str":
            out[c] = _series_as_str(s)
            continue
        if info.role == "binary_flag" and info.storage_dtype == "int":
            out[c] = pd.to_numeric(_series_as_str(s), errors="coerce").astype("Int64")
            continue
        if info.role in ("continuous_numeric", "discrete_count"):
            out[c] = pd.to_numeric(_series_as_str(s), errors="coerce")
            if info.storage_dtype == "int" or info.role == "discrete_count":
                out[c] = out[c].round().astype("Int64")
            continue
        if info.role == "datetime":
            out[c] = pd.to_datetime(_series_as_str(s), errors="coerce")
            continue
        if info.role == "categorical" and info.storage_dtype == "int":
            out[c] = pd.to_numeric(_series_as_str(s), errors="coerce").astype("Int64")
            continue
        out[c] = _series_as_str(s)
    return out


def parse_warning_for_role(info: ColumnRoleInfo, col: str) -> str | None:
    if info.role == "categorical":
        m = re.search(r"(\d+) values", info.why)
        n = m.group(1) if m else "?"
        return f"Column '{col}': categorical, {n} values"
    if info.role == "constant":
        return f"Column '{col}': constant: 1 value"
    if info.role == "id":
        return f"Column '{col}': id-like ({info.why})"
    if "mixed-type" in info.why:
        return f"Column '{col}': {info.why}"
    return None
