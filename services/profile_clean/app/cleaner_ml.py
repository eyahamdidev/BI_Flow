"""ML layer: imputation and outlier flagging (never delete unless YAML says drop)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import KNNImputer
from sklearn.neighbors import LocalOutlierFactor

from .column_roles import ColumnRoleInfo, role_allows_numeric_impute
from .config import RANDOM_STATE
from .lineage import LineageTracker
from .type_guard import (
    guard_mode_impute,
    guard_numeric_impute,
    guard_outlier,
    restore_column_dtype,
)


def _parse_col_ref(ref: str) -> tuple[str, str]:
    if "." in ref:
        t, c = ref.split(".", 1)
        return t, c
    return "", ref


def _save_impute_undo(state: Any, table: str, df: pd.DataFrame, id_col: str, col: str, mask: pd.Series) -> None:
    if state.undo_dir is None or not mask.any():
        return
    from pathlib import Path

    from .io_utils import write_parquet

    sub = Path(state.undo_dir)
    sub.mkdir(parents=True, exist_ok=True)
    undo = df.loc[mask, [id_col, col]].copy()
    undo.columns = ["row_id", "original_value"]
    write_parquet(undo, sub / f"{table}__impute__{col}.parquet")


def apply_imputation(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: Any,
    pk_map: dict[str, str],
    roles: dict[str, ColumnRoleInfo],
    original_dtypes: dict[str, dict[str, str]],
) -> None:
    strategies = rules.get("null_strategy", {})
    for key, spec in strategies.items():
        if not isinstance(spec, dict):
            continue
        strategy = spec.get("strategy", "")
        if strategy not in ("median", "knn_impute", "iterative_impute", "mode"):
            continue
        if "." not in key:
            continue
        t, col = key.split(".", 1)
        if t not in tables or col not in tables[t]:
            continue
        role = roles.get(key, ColumnRoleInfo("categorical", "unknown", "str"))
        df = tables[t]
        id_col = pk_map.get(t, df.columns[0])
        null_mask = df[col].isna()
        if not null_mask.any():
            continue
        flag_col = spec.get("imputed_flag", f"{col}__imputed")
        orig_dtype = original_dtypes.get(t, {}).get(col, str(df[col].dtype))
        n = int(null_mask.sum())

        if strategy == "mode":
            if not guard_mode_impute(role, t, col, state, lineage):
                continue
            fill = df[col].mode()
            val = fill.iloc[0] if len(fill) else "unknown"
            _save_impute_undo(state, t, df, id_col, col, null_mask)
            df.loc[null_mask, col] = val
            df[flag_col] = null_mask.astype(bool)
            step, rule = "impute_categorical", f"mode_impute({t}.{col})"
        else:
            if not guard_numeric_impute(role, t, col, df[col], state, lineage):
                continue
            if not role_allows_numeric_impute(role.role):
                continue
            allowed = spec.get("allowed", ["median"])
            method = strategy if strategy in allowed else allowed[0]
            numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != col]
            if method == "median":
                fill = df[col].median()
                _save_impute_undo(state, t, df, id_col, col, null_mask)
                df.loc[null_mask, col] = fill
                step, rule = "impute_numeric", f"median_impute({t}.{col})"
            elif method == "knn_impute" and len(numeric_cols) >= 1:
                imp = KNNImputer(n_neighbors=5)
                sub = df[[col] + numeric_cols[:10]].copy()
                filled = imp.fit_transform(sub)
                _save_impute_undo(state, t, df, id_col, col, null_mask)
                df[col] = filled[:, 0]
                step, rule = "impute_numeric", f"knn_impute({t}.{col}, k=5)"
            elif method == "iterative_impute" and len(numeric_cols) >= 1:
                from sklearn.experimental import enable_iterative_imputer  # noqa: F401
                from sklearn.impute import IterativeImputer

                imp = IterativeImputer(random_state=RANDOM_STATE)
                sub = df[[col] + numeric_cols[:10]].copy()
                _save_impute_undo(state, t, df, id_col, col, null_mask)
                df[col] = imp.fit_transform(sub)[:, 0]
                step, rule = "impute_numeric", f"iterative_impute({t}.{col})"
            else:
                fill = df[col].median()
                _save_impute_undo(state, t, df, id_col, col, null_mask)
                df.loc[null_mask, col] = fill
                step, rule = "impute_numeric", f"median_impute({t}.{col})"
            df[col] = restore_column_dtype(
                df[col],
                orig_dtype,
                is_integer=role.role in ("discrete_count", "binary_flag") or "int" in orig_dtype.lower(),
            )
            df[flag_col] = null_mask.astype(bool)

        tables[t] = df
        state.quality_log.append(
            {
                "rule_id": step,
                "table": t,
                "column": col,
                "method": "ml",
                "rows_affected": n,
                "imputation": strategy,
                "cells_imputed": n,
            }
        )
        lineage.emit(step, rule=rule, rows_affected=n, method="ml")


def apply_outliers(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: Any,
    roles: dict[str, ColumnRoleInfo],
) -> None:
    cfg = rules.get("outliers", {})
    if not cfg:
        return
    method = cfg.get("method", "iqr")
    action = cfg.get("action", "flag")
    cols = cfg.get("columns", [])
    discrete_outliers = bool(cfg.get("discrete_outliers", False))
    for ref in cols:
        t, col = _parse_col_ref(ref)
        if t not in tables or col not in tables[t]:
            continue
        key = f"{t}.{col}"
        role = roles.get(key, ColumnRoleInfo("continuous_numeric", "unknown", "float"))
        if not guard_outlier(role, t, col, tables[t][col], state, lineage, discrete_outliers=discrete_outliers):
            continue
        if pd.api.types.is_bool_dtype(tables[t][col]):
            continue
        s = pd.to_numeric(tables[t][col], errors="coerce").dropna()
        if s.empty or s.nunique() < 4:
            continue
        idx = tables[t].index
        series = pd.to_numeric(tables[t][col], errors="coerce")
        if method == "iqr":
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            bad = series.notna() & ((series < lo) | (series > hi))
        elif method == "mad":
            med = s.median()
            mad = (s - med).abs().median()
            if mad == 0:
                bad = pd.Series(False, index=idx)
            else:
                bad = series.notna() & ((series - med).abs() / mad > 3.5)
        elif method == "isolation_forest":
            X = series.fillna(series.median()).values.reshape(-1, 1)
            pred = IsolationForest(random_state=RANDOM_STATE, contamination=0.01).fit_predict(X)
            bad = pd.Series(pred == -1, index=idx)
        elif method == "lof":
            X = series.fillna(series.median()).values.reshape(-1, 1)
            pred = LocalOutlierFactor(n_neighbors=min(20, len(s) - 1), contamination=0.01).fit_predict(X)
            bad = pd.Series(pred == -1, index=idx)
        else:
            continue
        n = int(bad.sum())
        flag_col = f"{col}__outlier"
        if action == "flag":
            tables[t][flag_col] = bad.astype(bool)
            state.quality_log.append(
                {
                    "rule_id": "detect_outliers",
                    "table": t,
                    "column": col,
                    "method": method,
                    "rows_affected": n,
                    "outlier_method": method,
                }
            )
            lineage.emit("detect_outliers", rule=f"{method}({t}.{col})", rows_affected=n, method="ml")
        elif action == "drop":
            state.rows_dropped_by_table[t] = state.rows_dropped_by_table.get(t, 0) + n
            tables[t] = tables[t].loc[~bad].reset_index(drop=True)
