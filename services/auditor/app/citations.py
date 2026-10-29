"""Details behind one explain sentence. Every field is copied from the sheet or the event log."""

from __future__ import annotations

from typing import Any

from .fields import format_field, lookup
from .v7 import frame_values


def logged_lineage_events(sheet: dict[str, Any], events: list[dict[str, Any]] | None) -> list[str]:
    """Event ids whose rule or input name is already on the fact sheet. Nothing is inferred."""
    lineage = sheet.get("lineage") if isinstance(sheet.get("lineage"), dict) else {}
    rules = {str(item) for item in (lineage.get("cleaning_rules") or []) if isinstance(item, str)}
    tables = {str(item) for item in (lineage.get("raw_tables") or []) if isinstance(item, str)}
    found: list[str] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        labels = {str(event.get("rule") or ""), str(event.get("step") or "")}
        names: list[str] = []
        for key in ("inputs", "outputs"):
            refs = event.get(key) or []
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, dict):
                    names.append(str(ref.get("name") or ref.get("path") or ""))
                else:
                    names.append(str(ref))
        matched = bool(labels & rules) or any(table and table in name for table in tables for name in names)
        if not matched:
            continue
        token = str(event.get("event_id") or event.get("step") or "").strip()
        if token and token not in found:
            found.append(token)
    return found


def shown_value(sheet: dict[str, Any], path: str, lang: str = "en") -> str | None:
    values = frame_values(sheet, lang)
    if path in values:
        value = values[path]
        if path == "drivers.direction":
            return None if value is None else str(value)
        rendered = format_field(value, path, sheet)
        if rendered:
            return rendered
    found = lookup(sheet, path)
    return format_field(found, path, sheet)


def enrich_citations(
    citations: list[dict[str, Any]] | None,
    sheet: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
    lang: str = "en",
) -> list[dict[str, Any]]:
    definition = sheet.get("definition") if isinstance(sheet.get("definition"), dict) else {}
    sql = definition.get("sql") if isinstance(definition.get("sql"), str) and definition.get("sql").strip() else None
    lineage = sheet.get("lineage") if isinstance(sheet.get("lineage"), dict) else {}
    tables = [str(item) for item in (lineage.get("raw_tables") or []) if isinstance(item, str) and item.strip()]
    event = ", ".join(logged_lineage_events(sheet, events)) or None
    detailed: list[dict[str, Any]] = []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        facts = []
        for fact_id in citation.get("fact_ids") or []:
            path = str(fact_id)
            facts.append(
                {
                    "fact_id": path,
                    "value": shown_value(sheet, path, lang),
                    "lineage_event": event,
                    "sql": sql,
                    "source_tables": tables,
                }
            )
        detailed.append(
            {
                "sentence": citation.get("sentence"),
                "frame": citation.get("frame"),
                "fact_ids": [str(item) for item in (citation.get("fact_ids") or [])],
                "facts": facts,
            }
        )
    return detailed
