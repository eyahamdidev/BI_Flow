"""Semantic column recognition: role + semantic_type + confidence + evidence.

Deterministic only; LLM may suggest later via review queue. Auto-apply threshold
(default 0.9) is enforced by callers — below threshold → review item.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from .column_roles import ColumnRoleInfo, infer_column_role

AUTO_APPLY_THRESHOLD = 0.9

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
URL_RE = re.compile(r"^https?://", re.I)
IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CURRENCY_RE = re.compile(r"^[\s$€£¥R]?\(?-?\d[\d.,\s]*\)?[\s$€£¥%]?$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
DMY_RE = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}")
JSON_LIKE_RE = re.compile(r"^\s*[\[{]")
PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,20}$")

SENTINEL_TOKENS = {
    "unknown",
    "error",
    "missing",
    "not available",
    "n/a",
    "n.a.",
    "#n/a",
    "--",
    "na",
    "null",
    "none",
    "?",
    "-",
}


@dataclass
class ColumnRecognition:
    table: str
    column: str
    role: str
    semantic_type: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    proposed_action: str = "none"
    applied: bool = False
    storage_dtype: str = "str"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _str_series(s: pd.Series) -> pd.Series:
    return s.astype("string")


def _frac_match(ss: pd.Series, pattern: re.Pattern[str]) -> float:
    non = ss.dropna()
    if non.empty:
        return 0.0
    return float(non.str.match(pattern).mean())


def _detect_semantic(col: str, s: pd.Series, role_info: ColumnRoleInfo) -> tuple[str, float, list[str]]:
    cl = col.lower()
    ss = _str_series(s)
    non = ss.dropna()
    if role_info.role == "all_null":
        return "missing_all", 1.0, ["all values null"]
    if role_info.role == "constant":
        return "constant", 1.0, ["single distinct value"]

    if _frac_match(non, JSON_LIKE_RE) > 0.8:
        return "json_like", 0.92, ["cells look like JSON/list literals"]

    if "email" in cl or _frac_match(non, EMAIL_RE) > 0.85:
        return "email", max(0.85, _frac_match(non, EMAIL_RE)), ["email pattern match"]

    if "url" in cl or "website" in cl or _frac_match(non, URL_RE) > 0.7:
        return "url", 0.88, ["URL prefix match"]

    if "ip" in cl and _frac_match(non, IPV4_RE) > 0.7:
        return "ip_address", 0.9, ["IPv4 pattern"]

    if "phone" in cl or "mobile" in cl or _frac_match(non, PHONE_RE) > 0.75:
        return "phone", 0.85, ["phone-like digits"]

    if "uuid" in cl or _frac_match(non, UUID_RE) > 0.9:
        return "uuid", 0.95, ["UUID format"]

    if "lat" in cl and role_info.role in ("continuous_numeric", "discrete_count"):
        return "latitude", 0.9, ["name + numeric range heuristic"]
    if "lon" in cl or "lng" in cl:
        return "longitude", 0.9, ["name + numeric range heuristic"]

    if role_info.role == "id":
        if _has_letters(non):
            return "identifier_alphanumeric", 0.93, ["id role + letters in values"]
        return "identifier_integer", 0.92, ["id role + numeric"]

    if role_info.role == "binary_flag":
        return "boolean_flag", 0.95, ["two-value flag column"]

    if _frac_match(non, CURRENCY_RE) > 0.7 and any(x in cl for x in ("price", "amount", "cost", "fare", "revenue")):
        return "currency", 0.88, ["currency-like strings in money column"]

    if non.str.endswith("%").mean() > 0.5 or "percent" in cl or "pct" in cl:
        return "percentage", 0.87, ["percent suffix or column name"]

    if role_info.role == "datetime":
        amb = _date_ambiguity(non)
        if amb:
            return "datetime_ambiguous", 0.5, amb
        return "datetime", 0.9, ["parsed as datetime role"]

    if "country" in cl or "iso" in cl:
        return "country_code", 0.85, ["geographic name hint"]
    if "postal" in cl or "zip" in cl or "postcode" in cl:
        return "postal_code", 0.9, ["postal column name"]

    if "name" in cl and role_info.role in ("categorical", "free_text", "id"):
        return "person_or_entity_name", 0.8, ["name column — trim only"]

    if role_info.role == "categorical":
        n = int(non.nunique())
        return "categorical", 0.85, [f"low/medium cardinality ({n} values)"]

    if role_info.role == "continuous_numeric":
        return "continuous_numeric", 0.88, ["continuous numeric role"]

    if role_info.role == "discrete_count":
        return "discrete_count", 0.86, ["non-negative integer counts"]

    if role_info.role == "free_text":
        return "free_text", 0.9, ["high-cardinality text"]

    return "unknown", 0.5, ["fallback"]


def _has_letters(ss: pd.Series) -> bool:
    return bool(ss.str.contains(r"[A-Za-z]", regex=True).any())


def _date_ambiguity(non: pd.Series) -> list[str]:
    ev: list[str] = []
    dmy = non.str.match(DMY_RE)
    if not dmy.any():
        return ev
    samples = non[dmy].head(20)
    for val in samples:
        parts = re.split(r"[/.-]", str(val))
        if len(parts) >= 2:
            a, b = int(parts[0]), int(parts[1])
            if a <= 12 and b <= 12 and a != b:
                ev.append(f"ambiguous date sample {val} (day/month unclear)")
                break
    return ev


def recognize_table(
    table: str,
    df: pd.DataFrame,
    *,
    role_cfg: dict[str, Any] | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> list[ColumnRecognition]:
    overrides = overrides or {}
    out: list[ColumnRecognition] = []
    for col in df.columns:
        key = f"{table}.{col}"
        ov = overrides.get(key, {})
        if ov.get("role") and ov.get("semantic_type"):
            out.append(
                ColumnRecognition(
                    table=table,
                    column=col,
                    role=str(ov["role"]),
                    semantic_type=str(ov["semantic_type"]),
                    confidence=1.0,
                    evidence=["user override"],
                    proposed_action="none",
                    storage_dtype=str(ov.get("dtype", "str")),
                )
            )
            continue
        role_info = infer_column_role(col, df[col], role_cfg=role_cfg, n_rows=len(df))
        sem, conf, ev = _detect_semantic(col, df[col], role_info)
        if ov.get("semantic_type"):
            sem = str(ov["semantic_type"])
            conf = 1.0
        action = _proposed_action(sem, role_info.role, conf)
        out.append(
            ColumnRecognition(
                table=table,
                column=col,
                role=role_info.role,
                semantic_type=sem,
                confidence=conf,
                evidence=ev,
                proposed_action=action,
                storage_dtype=role_info.storage_dtype,
            )
        )
    return out


def _proposed_action(semantic: str, role: str, confidence: float) -> str:
    if confidence < AUTO_APPLY_THRESHOLD:
        return "review"
    if semantic in ("email", "url", "country_code"):
        return "standardise_format"
    if semantic in ("currency", "percentage") and confidence >= 0.9:
        return "parse_numeric"
    if semantic == "datetime_ambiguous":
        return "review"
    if semantic == "datetime" and confidence >= 0.9:
        return "normalise_date_iso"
    if semantic in (
        "identifier_alphanumeric",
        "identifier_integer",
        "person_or_entity_name",
        "free_text",
        "uuid",
        "json_like",
    ):
        return "none"
    if role == "id":
        return "none"
    if semantic == "categorical":
        return "trim_and_casefold_variants"
    return "standardise_safe"


def recognize_dataset(
    tables: dict[str, pd.DataFrame],
    ds_cfg: dict[str, Any] | None = None,
) -> list[ColumnRecognition]:
    cfg = (ds_cfg or {}).get("cleaning_rules", {}).get("role_inference", {})
    decisions = (ds_cfg or {}).get("decisions", {})
    overrides = decisions.get("column_overrides", {})
    rows: list[ColumnRecognition] = []
    for t, df in tables.items():
        rows.extend(recognize_table(t, df, role_cfg=cfg, overrides=overrides))
    return rows


def build_recognition_report(
    recognitions: list[ColumnRecognition],
    *,
    applied_ids: set[str] | None = None,
) -> dict[str, Any]:
    applied_ids = applied_ids or set()
    cols = []
    for r in recognitions:
        d = r.to_dict()
        rid = f"{r.table}.{r.column}"
        d["applied"] = rid in applied_ids or r.applied
        cols.append(d)
    return {"version": 1, "auto_apply_threshold": AUTO_APPLY_THRESHOLD, "columns": cols}


def load_decisions(ds_cfg: dict[str, Any]) -> dict[str, Any]:
    return ds_cfg.get("decisions", {})


def merge_decisions_into_config(cfg: dict[str, Any], decisions: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(cfg)
    cfg["decisions"] = decisions
    return cfg
