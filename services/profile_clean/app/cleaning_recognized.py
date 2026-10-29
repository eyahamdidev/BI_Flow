"""Apply safe cleaning steps guided by recognition (logged + undo)."""
from __future__ import annotations

import unicodedata
from typing import Any

import pandas as pd

from .cleaner_rules import CleanState, _log, _save_undo
from .lineage import LineageTracker
from .recognizer import AUTO_APPLY_THRESHOLD, SENTINEL_TOKENS, ColumnRecognition

MOJIBAKE_PAIRS = [("Ã©", "é"), ("Ã¨", "è"), ("Ã ", "à")]


def apply_sentinel_nulls(
    tables: dict[str, pd.DataFrame],
    recognitions: list[ColumnRecognition],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: CleanState,
    pk_map: dict[str, str],
) -> None:
    extra = set(rules.get("na_tokens", [])) | SENTINEL_TOKENS
    numeric_sentinels = set(str(x) for x in rules.get("numeric_sentinels", [-99, -999, 9999, 99999]))
    threshold = float(rules.get("auto_apply_confidence", AUTO_APPLY_THRESHOLD))
    for rec in recognitions:
        t, col = rec.table, rec.column
        if t not in tables or col not in tables[t]:
            continue
        df = tables[t]
        id_col = pk_map.get(t, df.columns[0])
        s = df[col].astype("string")
        mask = s.str.strip().str.lower().isin({x.lower() for x in extra})
        if rec.semantic_type in ("continuous_numeric", "discrete_count", "currency", "percentage"):
            num = pd.to_numeric(df[col], errors="coerce")
            for sentinel in numeric_sentinels:
                try:
                    sv = float(sentinel)
                    spike = num == sv
                    if spike.any() and spike.mean() < 0.05:
                        if rec.confidence < threshold:
                            state.review_queue.append(
                                {
                                    "table": t,
                                    "column": col,
                                    "issue": "numeric_sentinel",
                                    "suggested_action": "null",
                                    "reason": f"spike value {sentinel}",
                                    "source": "recognizer",
                                }
                            )
                        else:
                            mask = mask | spike
                except ValueError:
                    pass
        n = int(mask.sum())
        if n == 0:
            continue
        if rec.confidence >= threshold:
            _save_undo(state, t, "sentinel_null", df.loc[mask, [id_col, col]], id_col, col)
            df.loc[mask, col] = pd.NA
            _log(state, {"rule_id": "sentinel_to_null", "table": t, "column": col, "rows_affected": n})
            lineage.emit("sentinel_to_null", rule=f"null({t}.{col})", rows_affected=n)
        else:
            state.review_queue.append(
                {
                    "table": t,
                    "column": col,
                    "issue": "hidden_missing",
                    "suggested_action": "null",
                    "reason": f"confidence {rec.confidence:.2f} < {threshold}",
                    "source": "recognizer",
                }
            )
        tables[t] = df


def apply_standardise_recognized(
    tables: dict[str, pd.DataFrame],
    recognitions: list[ColumnRecognition],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: CleanState,
) -> None:
    threshold = float(rules.get("auto_apply_confidence", AUTO_APPLY_THRESHOLD))
    for rec in recognitions:
        if rec.confidence < threshold and rec.proposed_action != "none":
            continue
        t, col = rec.table, rec.column
        if t not in tables or col not in tables[t]:
            continue
        df = tables[t]
        if rec.semantic_type in (
            "person_or_entity_name",
            "identifier_alphanumeric",
            "identifier_integer",
            "free_text",
            "uuid",
        ):
            continue
        if rec.role == "id":
            continue
        if df[col].isna().all():
            continue
        if not (pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object):
            continue
        try:
            s = df[col].astype("string")
        except (TypeError, ValueError):
            continue
        cleaned = s.str.strip().str.replace(r"\s+", " ", regex=True)
        cleaned = cleaned.map(_nfc)
        if rec.semantic_type == "email":
            cleaned = cleaned.str.lower()
        if rec.semantic_type in ("url", "country_code"):
            cleaned = cleaned.str.lower()
        for bad, good in MOJIBAKE_PAIRS:
            cleaned = cleaned.str.replace(bad, good, regex=False)
        mask = s.notna() & (s != cleaned)
        n = int(mask.sum())
        if n:
            df[col] = cleaned
            _log(state, {"rule_id": "standardise", "table": t, "column": col, "rows_affected": n, "semantic": rec.semantic_type})
            lineage.emit("standardise", rule=f"{rec.semantic_type}({t}.{col})", rows_affected=n)
            tables[t] = df


def apply_category_maps(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    lineage: LineageTracker,
    state: CleanState,
    pk_map: dict[str, str],
) -> None:
    maps = rules.get("category_maps", {}) or {}
    for key, mapping in maps.items():
        if "." not in key or not isinstance(mapping, dict):
            continue
        t, col = key.split(".", 1)
        if t not in tables or col not in tables[t]:
            continue
        df = tables[t]
        id_col = pk_map.get(t, df.columns[0])
        before = df[col].astype("string")
        # exact-value lookup: .map() is one hash lookup per row; .replace(dict) with thousands of keys took
        # 137 s on the 1M-row geolocation table. Unmapped values keep their original text.
        mapped = before.map(mapping).fillna(before).astype("string")
        mask = before.notna() & (before != mapped)
        n = int(mask.sum())
        if n:
            _save_undo(state, t, "category_map", df.loc[mask, [id_col, col]], id_col, col)
            df[col] = mapped
            _log(state, {"rule_id": "category_map", "table": t, "column": col, "rows_affected": n, "mapping": mapping})
            lineage.emit("category_map", rule=f"map({t}.{col})", rows_affected=n)
            tables[t] = df


def apply_auto_review_maps(
    tables: dict[str, pd.DataFrame],
    state: CleanState,
    lineage: LineageTracker,
    pk_map: dict[str, str],
) -> None:
    """Apply review items marked auto_apply (case/accent category maps only)."""
    remaining = []
    for item in state.review_queue:
        if not item.get("auto_apply") or not item.get("proposed_mapping"):
            remaining.append(item)
            continue
        t, col = item["table"], item["column"]
        if t not in tables or col not in tables[t]:
            remaining.append(item)
            continue
        mapping = item["proposed_mapping"]
        df = tables[t]
        id_col = pk_map.get(t, df.columns[0])
        before = df[col].astype("string")
        # exact-value lookup: .map() is one hash lookup per row; .replace(dict) with thousands of keys took
        # 137 s on the 1M-row geolocation table. Unmapped values keep their original text.
        mapped = before.map(mapping).fillna(before).astype("string")
        mask = before.notna() & (before != mapped)
        n = int(mask.sum())
        if n:
            _save_undo(state, t, "category_auto", df.loc[mask, [id_col, col]], id_col, col)
            df[col] = mapped
            _log(state, {"rule_id": "category_map", "table": t, "column": col, "rows_affected": n, "auto": True})
            lineage.emit("category_map", rule=f"auto_accent({t}.{col})", rows_affected=n)
            tables[t] = df
    state.review_queue = remaining


def suggest_category_variants(
    tables: dict[str, pd.DataFrame],
    recognitions: list[ColumnRecognition],
    state: CleanState,
) -> None:
    """Case/accent-only clusters → auto map if unambiguous; typos → review."""
    for rec in recognitions:
        if rec.semantic_type != "categorical":
            continue
        t, col = rec.table, rec.column
        if t not in tables:
            continue
        s = tables[t][col].astype("string").dropna()
        if s.empty:
            continue
        canonical: dict[str, str] = {}
        groups: dict[str, list[str]] = {}
        for val in s.unique():
            key = unicodedata.normalize("NFKD", str(val)).encode("ascii", "ignore").decode("ascii").lower().strip()
            groups.setdefault(key, []).append(str(val))
        for _key, variants in groups.items():
            if len(variants) <= 1:
                continue
            if all(_accent_case_only(a, b) for b in variants[1:] for a in [variants[0]]):
                for v in variants:
                    canonical[v] = variants[0]
            else:
                state.review_queue.append(
                    {
                        "table": t,
                        "column": col,
                        "issue": "category_variants",
                        "suggested_action": "merge",
                        "reason": f"variants {variants[:5]}",
                        "source": "recognizer",
                        "proposed_mapping": {v: variants[0] for v in variants},
                    }
                )
        if canonical:
            state.review_queue.append(
                {
                    "table": t,
                    "column": col,
                    "issue": "category_case_accent",
                    "suggested_action": "auto_map",
                    "reason": "case/accent only",
                    "source": "recognizer",
                    "proposed_mapping": canonical,
                    "auto_apply": True,
                }
            )


def _accent_case_only(a: str, b: str) -> bool:
    na = unicodedata.normalize("NFKD", a).encode("ascii", "ignore").decode("ascii").lower().strip()
    nb = unicodedata.normalize("NFKD", b).encode("ascii", "ignore").decode("ascii").lower().strip()
    return na == nb


def _nfc(x: Any) -> Any:
    if pd.isna(x):
        return pd.NA
    return unicodedata.normalize("NFC", str(x))
