"""Advisory LLM layer: closed menu, YAML allow-list, review queue."""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from .config import MAX_LLM_CALLS_PER_RUN

try:
    from biflow_contracts.biflow_llm import LLMUnavailable, chat_json, drain_calls
except ImportError:
    from biflow_contracts.biflow_llm import LLMUnavailable, chat_json, drain_calls  # type: ignore[no-redef]


class ColumnAdvice(BaseModel):
    table: str
    column: str
    action: Literal["drop_column", "impute_median", "impute_mode", "flag", "ignore"]
    reason: str = Field(max_length=200)


class AdvisoryBatch(BaseModel):
    suggestions: list[ColumnAdvice]


def _compact_snippet(tables: dict[str, pd.DataFrame], profile: dict[str, Any] | None) -> str:
    lines = []
    if profile and "tables" in profile:
        for t, tp in list(profile["tables"].items())[:5]:
            lines.append(f"Table {t}: rows={tp.get('rows')}")
            for c, cp in list(tp.get("columns", {}).items())[:8]:
                if cp.get("null_pct", 0) > 1:
                    sample = ""
                    if t in tables and c in tables[t]:
                        vals = tables[t][c].dropna().head(3).tolist()
                        sample = f" samples={vals}"
                    lines.append(f"  - {c}: null_pct={cp.get('null_pct')}{sample}")
    return "\n".join(lines) or "No profile snippet available."


def run_llm_advisory(
    tables: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    profile: dict[str, Any] | None,
    lineage: Any,
    state: Any,
    protected_columns: set[tuple[str, str]],
    llm_calls_budget: list[int],
) -> list[Any]:
    cfg = rules.get("llm_advisory", {})
    if not cfg.get("enabled", True):
        return drain_calls()
    allowed = set(cfg.get("allowed_actions", ["impute_median", "impute_mode", "flag", "ignore"]))
    prompt_id = cfg.get("prompt_id", "profile_clean.suggest_advisory@v2")
    if llm_calls_budget[0] >= MAX_LLM_CALLS_PER_RUN:
        state.review_queue.append(
            {"table": "*", "column": "*", "issue": "llm_budget_exhausted", "source": "llm", "suggested_action": "ignore", "reason": "cap reached"}
        )
        return drain_calls()
    system = "You are a data cleaning advisor. Pick actions from the closed menu only."
    user = _compact_snippet(tables, profile)
    try:
        llm_calls_budget[0] += 1
        batch = chat_json(prompt_id, AdvisoryBatch, system=system, user=user, role="llm_fast", temperature=0.0)
    except (LLMUnavailable, Exception):
        if isinstance(getattr(state, "warnings", None), list):
            state.warnings.append("LLM advisory skipped: unreachable or invalid output")
        return drain_calls()

    for sug in batch.suggestions:
        key = (sug.table, sug.column)
        if sug.action == "drop_column" and key in protected_columns:
            state.review_queue.append(
                {
                    "table": sug.table,
                    "column": sug.column,
                    "issue": "protected_key",
                    "suggested_action": sug.action,
                    "reason": sug.reason,
                    "source": "llm",
                }
            )
            continue
        if sug.action not in allowed and sug.action != "drop_column":
            state.review_queue.append(
                {
                    "table": sug.table,
                    "column": sug.column,
                    "issue": "not_in_allow_list",
                    "suggested_action": sug.action,
                    "reason": sug.reason,
                    "source": "llm",
                }
            )
            continue
        if sug.action == "drop_column":
            state.review_queue.append(
                {
                    "table": sug.table,
                    "column": sug.column,
                    "issue": "drop_column_needs_review",
                    "suggested_action": sug.action,
                    "reason": sug.reason,
                    "source": "llm",
                }
            )
            continue
        if sug.table not in tables or sug.column not in tables[sug.table]:
            continue
        df = tables[sug.table]
        if sug.action == "impute_median" and pd.api.types.is_numeric_dtype(df[sug.column]):
            mask = df[sug.column].isna()
            if mask.any():
                med = df[sug.column].median()
                # an int column cannot hold a fractional median (pandas 3 raises): widen to float first
                if pd.api.types.is_integer_dtype(df[sug.column]) and float(med) != int(med):
                    df[sug.column] = df[sug.column].astype("float64")
                df.loc[mask, sug.column] = med
            lineage.emit("llm_advisory", rule=sug.action, rows_affected=int(mask.sum()), method="llm_assisted")
        elif sug.action == "impute_mode":
            mask = df[sug.column].isna()
            mode = df[sug.column].mode()
            if len(mode):
                df.loc[mask, sug.column] = mode.iloc[0]
            lineage.emit("llm_advisory", rule=sug.action, rows_affected=int(mask.sum()), method="llm_assisted")
        elif sug.action == "flag":
            df[f"{sug.column}__llm_flag"] = df[sug.column].isna()
            lineage.emit("llm_advisory", rule="flag", rows_affected=int(df[f"{sug.column}__llm_flag"].sum()), method="llm_assisted")
    return drain_calls()
