"""Fact sheets. Prose is allowed to use only what these functions put here."""

from __future__ import annotations

from typing import Any

from .graph_builder import upstream
from .io_utils import find_input, read_json


def as_definitions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("kpis") or payload.get("definitions") or []
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
        if payload.get("id"):
            return [payload]
    return []


def as_insights(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("insights")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def load_definitions(inputs: dict[str, str]) -> list[dict[str, Any]]:
    return as_definitions(read_json(find_input(inputs, "kpi_definitions", "kpi_definitions.json")))


def load_insights(inputs: dict[str, str]) -> list[dict[str, Any]]:
    return as_insights(read_json(find_input(inputs, "insights", "insights.json")))


def load_drivers(inputs: dict[str, str]) -> Any:
    return read_json(find_input(inputs, "drivers", "drivers.json"))


def load_graph(inputs: dict[str, str]) -> dict[str, Any]:
    payload = read_json(find_input(inputs, "lineage_graph", "lineage_graph.json"))
    return payload if isinstance(payload, dict) else {}


def load_manifest(run_id: str) -> dict[str, Any]:
    from .io_utils import data_dir

    payload = read_json(data_dir() / "runs" / run_id / "run_manifest.json")
    return payload if isinstance(payload, dict) else {}


def _drop_empty(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value is not None and value != "" and value != []}


def definition_for(definitions: list[dict[str, Any]], kpi_id: str) -> dict[str, Any] | None:
    for item in definitions:
        if str(item.get("id")) == kpi_id:
            kept = _drop_empty(
                {
                    "kpi_id": kpi_id,
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "sql": item.get("sql"),
                    "grain": item.get("grain"),
                    "unit": item.get("unit"),
                    "direction": item.get("direction"),
                    "dimensions": item.get("dimensions"),
                    "caveats": item.get("caveats"),
                    "synonyms": item.get("synonyms"),
                }
            )
            return kept or None
    return None


def _contribution(item: dict[str, Any]) -> dict[str, Any] | None:
    name = item.get("dimension_value", item.get("name", item.get("level")))
    delta = item.get("delta", item.get("contribution"))
    if name is None and delta is None:
        return None
    row: dict[str, Any] = {"dimension_value": name, "delta": delta}
    for key in ("value", "value_t", "value_prev"):
        if item.get(key) is not None:
            row[key] = item[key]
    return row


def _normalize_driver(row: dict[str, Any], kpi_id: str | None = None, period: str | None = None) -> dict[str, Any]:
    raw = row.get("contributions") or row.get("drivers") or []
    contributions = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                kept = _contribution(item)
                if kept:
                    contributions.append(kept)
    return _drop_empty(
        {
            "kpi_id": row.get("kpi_id") or kpi_id,
            "period": row.get("period") or period,
            "compare_to": row.get("compare_to"),
            "dimension": row.get("dimension"),
            "total_delta": row.get("total_delta", row.get("delta")),
            "contribution_count": len(contributions),
            "contributions": contributions,
        }
    )


def select_drivers(payload: Any, kpi_id: str, period: str, compare_to: str | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    if isinstance(payload, dict) and kpi_id in payload and not payload.get("kpi_id"):
        entry = payload[kpi_id]
        if isinstance(entry, dict) and period in entry and isinstance(entry[period], dict):
            row = _normalize_driver(entry[period], kpi_id, period)
            if compare_to and row.get("compare_to") not in (None, compare_to):
                return None
            return row
        if isinstance(entry, list):
            payload = entry
        elif isinstance(entry, dict) and ("contributions" in entry or "total_delta" in entry or "delta" in entry):
            payload = [entry]
    rows: list[dict[str, Any]]
    if isinstance(payload, list):
        rows = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("drivers"), list):
        rows = [item for item in payload["drivers"] if isinstance(item, dict)]
    elif isinstance(payload, dict) and (payload.get("kpi_id") or payload.get("contributions") or payload.get("total_delta") is not None):
        rows = [payload]
    else:
        return None
    matches = [row for row in rows if str(row.get("kpi_id") or kpi_id) == kpi_id and str(row.get("period") or period) == str(period)]
    if compare_to:
        narrowed = [row for row in matches if str(row.get("compare_to")) == str(compare_to)]
        if narrowed:
            matches = narrowed
    if not matches:
        return None
    return _normalize_driver(matches[0], kpi_id, period)


def public_insight(item: dict[str, Any]) -> dict[str, Any]:
    """Insight facts only. The narrative is someone else's prose, so it stays out of the fact sheet."""
    return _drop_empty(
        {
            "id": item.get("id"),
            "kpi_id": item.get("kpi_id"),
            "type": item.get("type"),
            "period": item.get("period"),
            "severity": item.get("severity"),
            "facts": item.get("facts") or {},
            "rule_id": item.get("rule_id"),
            "source": item.get("source"),
        }
    )


def insights_for(insights: list[dict[str, Any]], kpi_id: str, period: str | None) -> list[dict[str, Any]]:
    chosen = []
    for item in insights:
        if str(item.get("kpi_id")) != kpi_id:
            continue
        if period and item.get("period") not in (None, period):
            continue
        chosen.append(public_insight(item))
    return chosen


def compact_lineage(path: dict[str, Any]) -> dict[str, Any]:
    if not path.get("found"):
        return {"found": False}
    paths = path.get("paths") or []
    first = paths[0]["nodes"] if paths else []
    return _drop_empty(
        {
            "found": True,
            "raw_tables": path.get("raw_tables") or [],
            "cleaning_rules": path.get("cleaning_rules") or [],
            "dbt_models": path.get("dbt_models") or [],
            "kpi_sql": path.get("kpi_sql"),
            "path_count": len(paths),
            "path_nodes": first,
        }
    )


def explain_fact_sheet(
    *,
    kpi_id: str,
    period: str,
    compare_to: str | None,
    definitions: list[dict[str, Any]],
    graph: dict[str, Any],
    drivers_doc: Any,
    insights: list[dict[str, Any]],
) -> dict[str, Any]:
    lineage = compact_lineage(upstream(graph, kpi_id)) if graph.get("nodes") else {"found": False}
    matched = insights_for(insights, kpi_id, period)
    return _drop_empty(
        {
            "kpi_id": kpi_id,
            "period": period,
            "compare_to": compare_to,
            "definition": definition_for(definitions, kpi_id),
            "lineage": lineage,
            "drivers": select_drivers(drivers_doc, kpi_id, period, compare_to),
            "insights": matched,
            "insight_count": len(matched),
        }
    )


def sheet_is_empty(sheet: dict[str, Any]) -> bool:
    if sheet.get("definition") or sheet.get("drivers") or sheet.get("insights"):
        return False
    lineage = sheet.get("lineage") or {}
    return not (
        lineage.get("found")
        and (lineage.get("raw_tables") or lineage.get("cleaning_rules") or lineage.get("dbt_models") or lineage.get("kpi_sql") or lineage.get("path_nodes"))
    )


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _event_rows(refs: Any) -> int | None:
    if not isinstance(refs, list) or not refs:
        return None
    total = 0
    saw = False
    for ref in refs:
        if not isinstance(ref, dict):
            return None
        rows = _int_or_none(ref.get("rows"))
        if rows is None:
            return None
        total += rows
        saw = True
    return total if saw else None


def stage_sheet(title: str, agent: str, events: list[dict[str, Any]], duration_s: float | None) -> dict[str, Any]:
    steps = []
    for event in events:
        rule = event.get("rule") if isinstance(event.get("rule"), str) else None
        step = _drop_empty(
            {
                "step": event.get("step"),
                "rule": rule,
                "method": event.get("method") or "deterministic",
                "rows_in": _event_rows(event.get("inputs")),
                "rows_out": _event_rows(event.get("outputs")),
                "rows_affected": _int_or_none(event.get("rows_affected")),
            }
        )
        steps.append(step)
    sheet: dict[str, Any] = {"title": title, "agent": agent, "event_count": len(steps), "steps": steps}
    if duration_s is not None:
        sheet["duration_s"] = round(float(duration_s), 3)
    return sheet


def agent_duration(manifest: dict[str, Any], stages: list[str]) -> float | None:
    recorded = manifest.get("stages") or {}
    total = 0.0
    saw = False
    for name in stages:
        seconds = (recorded.get(name) or {}).get("seconds")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
            total += float(seconds)
            saw = True
    return round(total, 3) if saw else None


def kpi_sheet(definitions: list[dict[str, Any]], graph: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in definitions:
        kpi_id = str(item.get("id") or "")
        if not kpi_id:
            continue
        path = upstream(graph, kpi_id) if graph.get("nodes") else {}
        items.append(
            _drop_empty(
                {
                    "kpi_id": kpi_id,
                    "name": item.get("name") or kpi_id,
                    "description": item.get("description"),
                    "unit": item.get("unit"),
                    "sql": item.get("sql"),
                    "source_tables": path.get("raw_tables") or [],
                    "cleaning_steps": path.get("cleaning_rules") or [],
                    "dbt_models": path.get("dbt_models") or [],
                }
            )
        )
    return {"kpi_count": len(items), "kpis": items}


def insight_sheet(insights: list[dict[str, Any]]) -> dict[str, Any]:
    items = [public_insight(item) for item in insights if item.get("id")]
    return {"insight_count": len(items), "insights": items}


def quality_log_count(inputs: dict[str, str]) -> int | None:
    payload = read_json(find_input(inputs, "quality_log", "quality_log.json"))
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        fixes = payload.get("fixes") or payload.get("actions") or payload.get("entries")
        if isinstance(fixes, list):
            return len(fixes)
    return None
