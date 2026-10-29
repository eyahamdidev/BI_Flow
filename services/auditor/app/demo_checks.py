"""Pass/fail rules for the store demo. The shell script prints one line per check."""

from __future__ import annotations

from .constants import ABSTAIN


def store_hit_ok(result: dict, expected_text: str) -> bool:
    metrics = result.get("metrics") or {}
    calls = result.get("llm_calls") or []
    return metrics.get("explanation_store") == "hit" and metrics.get("answer") == expected_text and len(calls) == 0


def unreachable_fallback_ok(result: dict) -> bool:
    metrics = result.get("metrics") or {}
    warnings = result.get("warnings") or []
    return (
        metrics.get("explanation_store") == "miss"
        and metrics.get("prose_source") == "fallback"
        and any(str(item).strip() for item in warnings)
    )


def empty_sheet_ok(result: dict) -> bool:
    metrics = result.get("metrics") or {}
    return metrics.get("answer") == ABSTAIN and metrics.get("abstained") is True and metrics.get("explanation_store") == "abstain"
