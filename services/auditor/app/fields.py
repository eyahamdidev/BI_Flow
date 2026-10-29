"""Replace fact ids the model wrote with the logged value.

The model writes ``[drivers.total_delta]``. Code fills the number and, for a delta, the logged unit.
A model cannot invent ``units`` for a value whose unit is BRL.
"""

from __future__ import annotations

import re
from typing import Any

from .factcheck import canon

_FIELD = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)\]")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\[\d+\]")
_PERCENT_KEY = ("share", "rate", "ratio", "pct", "percent", "coverage")
_DELTA_KEY = {"delta", "total_delta"}
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _top_row(sheet: Any) -> dict[str, Any] | None:
    drivers = sheet.get("drivers") if isinstance(sheet, dict) else None
    rows = drivers.get("contributions") if isinstance(drivers, dict) else None
    if not isinstance(rows, list):
        return None
    best: dict[str, Any] | None = None
    best_delta: float | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        delta = row.get("delta")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)):
            continue
        if best_delta is None or float(delta) > best_delta:
            best_delta = float(delta)
            best = row
    return best


def lookup(sheet: Any, path: str) -> Any:
    if path == "drivers.top.label":
        row = _top_row(sheet)
        if row is None or row.get("dimension_value") is None:
            return None
        return row.get("dimension_value")
    if path == "drivers.top.delta":
        row = _top_row(sheet)
        return None if row is None else row.get("delta")
    current = sheet
    for token in _TOKEN.findall(path or ""):
        if token.startswith("["):
            if not isinstance(current, list):
                return None
            index = int(token[1:-1])
            if index >= len(current):
                return None
            current = current[index]
            continue
        if not isinstance(current, dict) or token not in current:
            return None
        current = current[token]
    return current


def _leaf(path: str) -> str:
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)$", path or "")
    return match.group(1) if match else ""


def format_field(value: Any, path: str, sheet: dict[str, Any]) -> str | None:
    """Render one logged field. Deltas are followed by ``definition.unit`` when that unit was logged."""
    if isinstance(value, bool) or value is None or isinstance(value, dict):
        return None
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, (dict, list)) or isinstance(item, bool) or item is None:
                return None
            parts.append(format_field(item, path, sheet) or "")
        return ", ".join(part for part in parts if part)
    if isinstance(value, str):
        return value
    if not isinstance(value, (int, float)):
        return None
    leaf = _leaf(path).lower()
    if any(token in leaf for token in _PERCENT_KEY):
        shown = value * 100 if abs(float(value)) <= 1 else value
        return f"{canon(float(shown))}%"
    text = canon(float(value))
    if leaf in _DELTA_KEY:
        unit = lookup(sheet, "definition.unit")
        if isinstance(unit, str) and unit.strip():
            return f"{text} {unit.strip()}"
    return text


def valid_ids(sheet: dict[str, Any]) -> list[str]:
    """Every id the model may write. `drivers.top.label` names the largest contribution."""
    lines: list[str] = []
    if _top_row(sheet) is not None:
        lines.extend(["drivers.top.label", "drivers.top.delta"])

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                walk(value, f"{path}.{key}" if path else str(key))
            return
        if isinstance(obj, list):
            for index, value in enumerate(obj):
                walk(value, f"{path}[{index}]")
            return
        if path and not isinstance(obj, bool):
            lines.append(path)

    walk(sheet, "")
    return lines


def field_catalog(sheet: dict[str, Any]) -> str:
    """Ids the model is allowed to cite. Values stay in the fact sheet, not in this list."""
    return "\n".join(f"- {line}" for line in valid_ids(sheet))


def fill_fact_ids(prose: str, sheet: dict[str, Any]) -> tuple[str, list[str]]:
    """Substitute every ``[path]``. An unknown path is reported and left in place."""
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        value = lookup(sheet, path)
        rendered = format_field(value, path, sheet) if value is not None else None
        if rendered is None:
            token = f"placeholder:{path}"
            if token not in missing:
                missing.append(token)
            return match.group(0)
        return rendered

    return _FIELD.sub(replace, prose or ""), missing


def declared_citations(raw: str, filled: str, sheet: dict[str, Any]) -> list[dict[str, Any]]:
    """Citations the model declared, paired with the sentence after substitution."""
    raw_sentences = [part for part in _SENTENCE.split((raw or "").strip()) if part.strip()]
    filled_sentences = [part for part in _SENTENCE.split((filled or "").strip()) if part.strip()]
    if len(raw_sentences) != len(filled_sentences):
        filled_sentences = raw_sentences
    cited = []
    for original, sentence in zip(raw_sentences, filled_sentences, strict=False):
        ids = []
        for path in _FIELD.findall(original):
            if format_field(lookup(sheet, path), path, sheet) is not None and path not in ids:
                ids.append(path)
        cited.append({"sentence": sentence, "fact_ids": ids})
    return cited
