"""Deterministic draft dataset YAML for uploaded tables (playground only)."""
from __future__ import annotations

from typing import Any

import pandas as pd
import yaml
from app.column_roles import (
    ColumnRoleInfo,
    infer_table_roles,
    role_allows_outliers,
)

ALLOWED_TOP = {"name", "domain", "source", "expected_schema", "relationships", "cleaning_rules"}


def _null_pct(series: pd.Series) -> float:
    return 100.0 * series.isna().sum() / max(len(series), 1)


def suggest_primary_keys(tables: dict[str, pd.DataFrame], roles: dict[str, ColumnRoleInfo]) -> dict[str, str]:
    out: dict[str, str] = {}
    for t, df in tables.items():
        for c in df.columns:
            key = f"{t}.{c}"
            if roles.get(key) and roles[key].role == "id":
                out[t] = c
                break
        if t not in out and len(df.columns):
            out[t] = df.columns[0]
    return out


def suggest_relationships(tables: dict[str, pd.DataFrame], pks: dict[str, str]) -> list[dict[str, str]]:
    rels: list[dict[str, str]] = []
    cols_by_table = {t: set(df.columns) for t, df in tables.items()}
    for t, df in tables.items():
        for c in df.columns:
            if not c.lower().endswith("_id") or c == pks.get(t):
                continue
            target_col = c
            for ot, ocols in cols_by_table.items():
                if ot == t:
                    continue
                if target_col in ocols:
                    left = df[c].dropna().astype(str)
                    right = tables[ot][target_col].dropna().astype(str)
                    if len(left) and left.isin(right).mean() >= 0.5:
                        rels.append({"from": f"{t}.{c}", "to": f"{ot}.{target_col}"})
    return rels[:20]


def generate_draft_yaml(
    dataset_name: str,
    tables: dict[str, pd.DataFrame],
    profile: dict[str, Any] | None,
    *,
    null_threshold: float = 60.0,
    outlier_method: str = "iqr",
    allow_knn: bool = False,
    allow_drop_dupes: bool = True,
    llm_enabled: bool = False,
    protect_columns: list[str] | None = None,
    role_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    protect = set(protect_columns or [])
    role_overrides = role_overrides or {}
    role_cfg = {"high_null_pct": null_threshold}
    table_roles: dict[str, dict[str, ColumnRoleInfo]] = {}
    flat_roles: dict[str, ColumnRoleInfo] = {}
    for t, df in tables.items():
        tr = infer_table_roles(df, role_cfg)
        for c, info in tr.items():
            key = f"{t}.{c}"
            if key in role_overrides:
                info = ColumnRoleInfo(role_overrides[key], f"user override to {role_overrides[key]}", info.storage_dtype)
            flat_roles[key] = info
        table_roles[t] = {c: flat_roles[f"{t}.{c}"] for c in df.columns}

    pks = suggest_primary_keys(tables, flat_roles)
    expected: dict[str, Any] = {}
    null_strategy: dict[str, Any] = {}
    date_cols: list[str] = []
    trim_targets: dict[str, list[str]] = {}
    outlier_cols: list[str] = []
    impossible: list[dict[str, Any]] = []

    for t, df in tables.items():
        expected[t] = {}
        prof_t = (profile or {}).get("tables", {}).get(t, {})
        prof_cols = prof_t.get("columns", {})
        for c in df.columns:
            key = f"{t}.{c}"
            info = flat_roles[key]
            expected[t][c] = {"dtype": info.storage_dtype, "role": info.role, "why": info.why}
            null_p = prof_cols.get(c, {}).get("null_pct", _null_pct(df[c]))
            if c in protect:
                null_strategy[key] = {"strategy": "flag_only", "flag_column": f"{c}_missing_flag"}
                continue

            if info.role in ("id", "free_text", "datetime", "binary_flag", "constant", "all_null"):
                null_strategy[key] = {
                    "strategy": "flag_only",
                    "flag_column": f"{c}__high_null" if null_p > null_threshold else f"{c}_missing_flag",
                }
            elif null_p > null_threshold:
                null_strategy[key] = {"strategy": "flag_only", "flag_column": f"{c}__high_null"}
            elif info.role == "categorical":
                null_strategy[key] = {"strategy": "mode", "imputed_flag": f"{c}__imputed"}
            elif info.role == "discrete_count":
                null_strategy[key] = {
                    "strategy": "median",
                    "allowed": ["median"],
                    "imputed_flag": f"{c}__imputed",
                }
            elif info.role == "continuous_numeric":
                allowed = ["median", "knn_impute"] if allow_knn else ["median"]
                null_strategy[key] = {"strategy": "median", "allowed": allowed, "imputed_flag": f"{c}__imputed"}
                if "price" in c.lower() or "amount" in c.lower() or "fare" in c.lower():
                    impossible.append(
                        {"table": t, "column": c, "rule": ">= 0", "action": "flag", "flag_column": f"{c}__invalid"}
                    )
                if role_allows_outliers(info.role):
                    outlier_cols.append(f"{t}.{c}")
            else:
                null_strategy[key] = {"strategy": "flag_only", "flag_column": f"has_{c}"}

            if info.role == "datetime":
                date_cols.append(c)
            if info.storage_dtype == "str" or df[c].dtype == object:
                trim_targets.setdefault(t, []).append(c)

    cfg: dict[str, Any] = {
        "name": dataset_name,
        "domain": "upload",
        "source": {
            "type": "csv",
            "path": f"data/uploads/{dataset_name}",
            "tables": {t: f"{t}.csv" for t in tables},
        },
        "expected_schema": expected,
        "relationships": suggest_relationships(tables, pks),
        "cleaning_rules": {
            "primary_keys": pks,
            "role_inference": {"high_null_pct": null_threshold},
            "parse_dates": sorted(set(date_cols)),
            "trim_strings": trim_targets,
            "drop_exact_duplicates": list(tables.keys()) if allow_drop_dupes else [],
            "null_strategy": null_strategy,
            "impossible_values": impossible,
            "outliers": {
                "method": outlier_method,
                "columns": outlier_cols[:30],
                "action": "flag",
                "discrete_outliers": False,
            },
            "llm_advisory": {
                "enabled": llm_enabled,
                "allowed_actions": ["impute_median", "impute_mode", "flag", "ignore"],
            },
        },
    }
    return cfg


def yaml_dump(cfg: dict[str, Any]) -> str:
    return yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, default_flow_style=False)


def validate_yaml_structure(cfg: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    extra = set(cfg) - ALLOWED_TOP
    if extra:
        errs.append(f"Unknown top-level keys: {extra}")
    if "cleaning_rules" not in cfg:
        errs.append("missing cleaning_rules")
    return errs


def id_columns_from_yaml(cfg: dict[str, Any]) -> set[str]:
    pks = cfg.get("cleaning_rules", {}).get("primary_keys", {})
    return {f"{t}.{c}" for t, c in pks.items()}
