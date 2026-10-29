"""YAML-driven deterministic cleaning rules."""
from __future__ import annotations

import unicodedata
from typing import Any

import numpy as np
import pandas as pd

from .io_utils import write_parquet
from .lineage import LineageTracker


def _normalize_accents(s: str) -> str:
    nf = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nf if not unicodedata.combining(c))


class CleanState:
    def __init__(self) -> None:
        self.quality_log: list[dict[str, Any]] = []
        self.review_queue: list[dict[str, Any]] = []
        self.dropped_rows: list[dict[str, Any]] = []
        self.rows_dropped_by_table: dict[str, int] = {}
        self.undo_dir: str | None = None
        self.warnings: list[str] = []


def _log(state: CleanState, entry: dict[str, Any]) -> None:
    state.quality_log.append(entry)


def _save_undo(state: CleanState, table: str, rule_id: str, df: pd.DataFrame, id_col: str, value_col: str) -> None:
    if state.undo_dir is None:
        return
    from pathlib import Path

    sub = Path(state.undo_dir)
    sub.mkdir(parents=True, exist_ok=True)
    undo = df[[id_col, value_col]].copy()
    undo.columns = ["row_id", "original_value"]
    write_parquet(undo, sub / f"{table}__{rule_id}.parquet")


def apply_parse_dates(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: CleanState,
) -> None:
    cols_by_table: dict[str, list[str]] = {}
    for item in rules.get("parse_dates", []):
        if isinstance(item, str):
            for t, df in tables.items():
                if item in df.columns:
                    cols_by_table.setdefault(t, []).append(item)
        elif isinstance(item, dict):
            t = item.get("table", "")
            cols_by_table.setdefault(t, []).extend(item.get("columns", []))

    for t, cols in cols_by_table.items():
        if t not in tables:
            continue
        for col in cols:
            if col not in tables[t].columns:
                continue
            before = tables[t][col].copy()
            parsed = pd.to_datetime(tables[t][col], errors="coerce")
            nat = int(parsed.isna().sum() - before.isna().sum())
            tables[t][col] = parsed
            _log(
                state,
                {
                    "rule_id": "parse_dates",
                    "table": t,
                    "column": col,
                    "rows_affected": nat,
                    "method": "deterministic",
                    "detail": f"coerced {nat} values to NaT",
                },
            )
            lineage.emit("parse_dates", rule=f"to_datetime({t}.{col})", rows_affected=nat)


def apply_trim_strings(tables: dict[str, pd.DataFrame], rules: dict[str, Any], lineage: LineageTracker, state: CleanState) -> None:
    spec = rules.get("trim_strings", {})
    if spec is True:
        targets = {t: list(df.select_dtypes(include=["object", "string"]).columns) for t, df in tables.items()}
    elif isinstance(spec, dict):
        targets = spec
    else:
        return
    for t, cols in targets.items():
        if t not in tables:
            continue
        affected = 0
        for col in cols:
            if col not in tables[t].columns:
                continue
            s = tables[t][col].astype("string")
            cleaned = s.str.strip().str.replace(r"\s+", " ", regex=True)
            if rules.get("string_case", {}).get(t, {}).get(col) == "lower":
                cleaned = cleaned.str.lower()
            mask = s.notna() & (s != cleaned)
            affected += int(mask.sum())
            tables[t][col] = cleaned
        if affected:
            _log(state, {"rule_id": "trim_strings", "table": t, "rows_affected": affected, "method": "deterministic"})
            lineage.emit("trim_strings", rule=f"strip({t})", rows_affected=affected)


def apply_rename_columns(tables: dict[str, pd.DataFrame], rules: dict[str, Any], lineage: LineageTracker, state: CleanState) -> None:
    renames = rules.get("rename_columns", {})
    for t, mapping in renames.items():
        if t not in tables:
            continue
        present = {k: v for k, v in mapping.items() if k in tables[t].columns}
        if not present:
            continue
        tables[t] = tables[t].rename(columns=present)
        _log(state, {"rule_id": "rename_columns", "table": t, "mapping": present, "method": "deterministic"})
        lineage.emit("rename_columns", rule=f"rename({t})", params=present)


def apply_drop_duplicates(tables: dict[str, pd.DataFrame], rules: dict[str, Any], lineage: LineageTracker, state: CleanState) -> None:
    for t in rules.get("drop_exact_duplicates", []):
        if t not in tables:
            continue
        before = len(tables[t])
        tables[t] = tables[t].drop_duplicates()
        dropped = before - len(tables[t])
        if dropped:
            state.rows_dropped_by_table[t] = state.rows_dropped_by_table.get(t, 0) + dropped
            for _ in range(min(dropped, 5)):
                state.dropped_rows.append({"table": t, "rule_id": "drop_exact_duplicates", "row_id": None})
            _log(state, {"rule_id": "drop_exact_duplicates", "table": t, "rows_affected": dropped, "method": "deterministic"})
            lineage.emit("drop_exact_duplicates", rule=f"drop_duplicates({t})", rows_affected=dropped)


def apply_dedupe(tables: dict[str, pd.DataFrame], rules: dict[str, Any], lineage: LineageTracker, state: CleanState) -> None:
    dedupe_cfg = rules.get("dedupe", {})
    for t, cfg in dedupe_cfg.items():
        if t not in tables or not isinstance(cfg, dict):
            continue
        key = cfg.get("key")
        if not key or key not in tables[t].columns:
            continue
        df = tables[t]
        if "geolocation_city" in df.columns or "geolocation_city" in cfg.get("normalize_city", []):
            city_col = "geolocation_city" if "geolocation_city" in df.columns else None
            if city_col:
                df[city_col] = df[city_col].astype("string").map(lambda x: _normalize_accents(x) if pd.notna(x) else x)
        agg = cfg.get("agg", {})
        before = len(df)
        agg_dict: dict[str, str] = {}
        for col in df.columns:
            if col == key:
                continue
            fn = agg.get(col, "first")
            agg_dict[col] = "mean" if fn == "mean" else "first"
        out = df.groupby(key, as_index=False).agg(agg_dict)
        tables[t] = out
        collapsed = before - len(out)
        if collapsed:
            state.rows_dropped_by_table[t] = state.rows_dropped_by_table.get(t, 0) + collapsed
        _log(state, {"rule_id": "dedupe", "table": t, "rows_affected": collapsed, "method": "deterministic", "key": key})
        lineage.emit("dedupe_geolocation" if t == "geolocation" else "dedupe", rule=f"groupby({key})", rows_affected=collapsed)


def apply_category_translation(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: CleanState,
) -> None:
    if "products" not in tables or "category_translation" not in tables:
        return
    trans = tables["category_translation"].drop_duplicates("product_category_name")
    mapping = dict(zip(trans["product_category_name"], trans["product_category_name_english"], strict=False))
    fixes = rules.get("category_mapping_fixes", {})
    mapping.update(fixes)
    prod = tables["products"]
    if "product_category_name" not in prod.columns:
        return
    if "product_category_name_english" not in prod.columns:
        prod["product_category_name_english"] = np.nan
    before_null = int(prod["product_category_name_english"].isna().sum())
    mapped = prod["product_category_name"].map(mapping)
    prod["product_category_name_english"] = mapped.combine_first(prod["product_category_name_english"])
    filled = before_null - int(prod["product_category_name_english"].isna().sum())
    _log(state, {"rule_id": "translate_category_names", "table": "products", "rows_affected": filled, "method": "deterministic"})
    lineage.emit("translate_category_names", rule="map(category_translation)", rows_affected=filled)
    for src, tgt in fixes.items():
        mask = prod["product_category_name"] == src
        if mask.any():
            _log(state, {"rule_id": "category_mapping_fixes", "table": "products", "rows_affected": int(mask.sum()), "mapping": {src: tgt}})
            lineage.emit("category_mapping_fixes", rule=f"fix({src})", rows_affected=int(mask.sum()))


def apply_null_strategy(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: CleanState,
    pk_map: dict[str, str],
) -> None:
    strategies = rules.get("null_strategy", {})
    for key, spec in strategies.items():
        if "." not in key:
            continue
        t, col = key.split(".", 1)
        if t not in tables or col not in tables[t]:
            continue
        if isinstance(spec, str):
            strategy = spec
            extra: dict[str, Any] = {}
        else:
            strategy = spec.get("strategy", "flag_only")
            extra = spec
        if strategy in ("median", "mode", "knn_impute", "iterative_impute"):
            continue
        df = tables[t]
        id_col = pk_map.get(t, df.columns[0])
        null_mask = df[col].isna()
        n = int(null_mask.sum())
        if n == 0:
            continue
        if strategy == "flag_only":
            flag = extra.get("flag_column", f"{col}_missing_flag" if "date" in col else f"has_{col}")
            if col == "review_comment_message":
                flag = extra.get("flag_column", "has_comment")
                df[flag] = df[col].notna()
            elif col == "order_delivered_customer_date":
                flag = extra.get("flag_column", "delivery_missing_flag")
                df[flag] = null_mask
            else:
                df[flag] = null_mask
            _log(state, {"rule_id": "null_strategy", "table": t, "column": col, "strategy": "flag_only", "rows_affected": n})
            lineage.emit("null_strategy", rule=f"flag_only({t}.{col})", rows_affected=n)
        elif strategy == "constant":
            val = extra.get("value", "unknown")
            _save_undo(state, t, "null_constant", df.loc[null_mask, [id_col, col]], id_col, col)
            df.loc[null_mask, col] = val
            _log(state, {"rule_id": "null_strategy", "table": t, "column": col, "strategy": "constant", "value": val, "rows_affected": n})
            lineage.emit("null_strategy", rule=f"constant({val})", rows_affected=n)
        elif strategy == "drop":
            drop_idx = df.index[null_mask]
            for idx in drop_idx[:1000]:
                state.dropped_rows.append({"table": t, "rule_id": "null_strategy_drop", "row_id": str(df.at[idx, id_col])})
            state.rows_dropped_by_table[t] = state.rows_dropped_by_table.get(t, 0) + n
            tables[t] = df.loc[~null_mask].reset_index(drop=True)
            _log(state, {"rule_id": "null_strategy", "table": t, "column": col, "strategy": "drop", "rows_affected": n})
            lineage.emit("null_strategy", rule="drop_nulls", rows_affected=n)
        tables[t] = df


def apply_impossible_values(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: CleanState,
) -> None:
    for rule in rules.get("impossible_values", []):
        t = rule.get("table")
        if not t or t not in tables:
            continue
        action = rule.get("action", "flag")
        df = tables[t]
        if "column" in rule and "rule" in rule:
            col = rule["column"]
            expr = rule["rule"]
            if col not in df.columns:
                continue
            if expr.strip().startswith(">="):
                thresh = float(expr.replace(">=", "").strip())
                bad = df[col] < thresh
            else:
                continue
        elif "rule" in rule and ">=" in rule["rule"]:
            parts = rule["rule"].split(">=")
            left, right = parts[0].strip(), parts[1].strip()
            if left not in df.columns or right not in df.columns:
                continue
            bad = df[left].notna() & df[right].notna() & (df[left] < df[right])
            col = f"bad_{left}_before_{right}"
        else:
            continue
        n = int(bad.sum())
        if n == 0:
            continue
        flag_col = rule.get("flag_column", f"{col}__invalid" if "column" in rule else col)
        if action == "flag":
            df[flag_col] = bad
            _log(state, {"rule_id": "impossible_values", "table": t, "column": flag_col, "rows_affected": n, "method": "deterministic"})
            lineage.emit("flag_impossible_values", rule=str(rule.get("rule")), rows_affected=n)
        elif action == "drop":
            state.rows_dropped_by_table[t] = state.rows_dropped_by_table.get(t, 0) + n
            tables[t] = df.loc[~bad].reset_index(drop=True)
            lineage.emit("flag_impossible_values", rule="drop", rows_affected=n)
        else:
            tables[t] = df


def apply_rules(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: CleanState,
    pk_map: dict[str, str],
) -> None:
    apply_rename_columns(tables, rules, lineage, state)
    apply_parse_dates(tables, rules, lineage, state)
    apply_trim_strings(tables, rules, lineage, state)
    apply_drop_duplicates(tables, rules, lineage, state)
    apply_dedupe(tables, rules, lineage, state)
    apply_category_translation(tables, rules, lineage, state)
    apply_null_strategy(tables, rules, lineage, state, pk_map)
    apply_impossible_values(tables, rules, lineage, state)
