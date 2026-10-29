"""Deterministic fact-check. No model is involved.

`missing_numbers` is the loose digit check: `8%` passes when the sheet contains `8` or `0.08`.
`unsupported_claims` is what the service publishes. A percent has to belong to a rate,
the direction has to match the sign of the delta, a "top driver" has to be the largest
contribution, and a state, category, or dataset name has to occur in the sheet.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import yaml

_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])([+-]?(?:\d{1,3}(?:[ ,]\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?)(%)?(?![A-Za-z0-9_])"
)


def canon(value: float) -> str:
    if abs(value) < 1e-12:
        return "0"
    if abs(value - round(value)) < 1e-9 * max(1.0, abs(value)):
        return str(int(round(value)))
    return f"{value:.8f}".rstrip("0").rstrip(".")


def extract_numbers(text: str) -> list[tuple[str, bool]]:
    """Return (canonical number, was written with a percent sign), in order."""
    found: list[tuple[str, bool]] = []
    for match in _NUMBER.finditer(text or ""):
        raw = match.group(1).replace(" ", "").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        found.append((canon(value), bool(match.group(2))))
    return found


def sheet_numbers(obj: Any, bucket: set[str] | None = None) -> set[str]:
    bucket = set() if bucket is None else bucket
    if isinstance(obj, bool) or obj is None:
        return bucket
    if isinstance(obj, (int, float)):
        if math.isfinite(float(obj)):  # a NaN/inf in a fact sheet is not a citable number (and canon() cannot format it)
            bucket.add(canon(float(obj)))
            if float(obj) < 0:  # "went down by 42489.58" states the size of a -42489.58 change; the sign is checked
                bucket.add(canon(abs(float(obj))))  # separately by the direction rule (a wrong "went up" is still caught)
        return bucket
    if isinstance(obj, str):
        for number, _percent in extract_numbers(obj):
            bucket.add(number)
        return bucket
    if isinstance(obj, dict):
        for value in obj.values():
            sheet_numbers(value, bucket)
        return bucket
    if isinstance(obj, (list, tuple)):
        for value in obj:
            sheet_numbers(value, bucket)
    return bucket


def missing_numbers(prose: str, fact_sheet: Any) -> list[str]:
    """Numbers written in `prose` that the fact sheet does not contain.

    This is the loose digit check: `8%` passes when the sheet contains `8` or `0.08`.
    `unsupported_claims` is the check the service publishes.
    """
    allowed = sheet_numbers(fact_sheet)
    missing: list[str] = []
    seen: set[str] = set()
    for number, is_percent in extract_numbers(prose):
        if number in allowed:
            continue
        if is_percent and canon(float(number) / 100.0) in allowed:
            continue
        token = f"{number}%" if is_percent else number
        if token not in seen:
            seen.add(token)
            missing.append(token)
    return missing


_PERCENT_KEY = ("share", "rate", "ratio", "pct", "percent", "coverage")
_STATES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}
_WORD = re.compile(r"[A-Za-zÀ-ÿ']+")
_RANK = re.compile(
    r"\b(?:top|largest|biggest|highest|leading|main)\s+(?:logged\s+)?"
    r"(?:driver|contribution|contributor)s?\s+(?:is|was|came from)\s+"
    r"(?:(?:the|state|of|logged)\s+){0,4}"
    r"([A-Za-z][A-Za-z0-9_-]*)",
    re.I,
)
_SNAKE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")
_NODE = re.compile(r"\b((?:raw|clean|dbt|kpi|ins|profile|quality)\.[A-Za-z0-9_.]+)\b")


def _lexicon() -> dict[str, Any]:
    path = Path(__file__).with_name("direction_words.yaml")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


_LEX = _lexicon()
_UP = {str(word).lower() for word in _LEX.get("up") or []}
_DOWN = {str(word).lower() for word in _LEX.get("down") or []}
_UP_PHRASES = [str(phrase).lower() for phrase in _LEX.get("up_phrases") or []]
_DOWN_PHRASES = [str(phrase).lower() for phrase in _LEX.get("down_phrases") or []]
_CAUSE_FIELDS = {str(name) for name in _LEX.get("cause_fields") or []}
_CAUSE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(str(phrase)) for phrase in sorted(_LEX.get("cause_connectives") or [], key=len, reverse=True))
    + r")\b",
    re.I,
)
_PLACEHOLDER = re.compile(r"\[[^\]]+\]")


def _evaluative_lexicon() -> list[str]:
    path = Path(__file__).with_name("evaluative_words.yaml")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    words: list[str] = []
    if isinstance(loaded, dict):
        for value in loaded.values():
            if isinstance(value, list):
                words.extend(str(item).strip().lower() for item in value if str(item).strip())
    return sorted(set(words), key=len, reverse=True)


_EVALUATIVE = _evaluative_lexicon()


def evaluative_hits(prose: str) -> list[str]:
    """Listed commentary words that sit outside an id placeholder."""
    outside = _PLACEHOLDER.sub(" ", prose or "")
    hits: list[str] = []
    for word in _EVALUATIVE:
        if re.search(rf"\b{re.escape(word)}\b", outside, re.I) and word not in hits:
            hits.append(word)
    return hits


def _remember(items: list[str], seen: set[str], token: str) -> None:
    if token and token not in seen:
        seen.add(token)
        items.append(token)


def _numeric_fields(obj: Any, found: list[tuple[str, float]] | None = None) -> list[tuple[str, float]]:
    found = [] if found is None else found
    if isinstance(obj, bool) or obj is None:
        return found
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                found.append((str(key), float(value)))
            else:
                _numeric_fields(value, found)
        return found
    if isinstance(obj, (list, tuple)):
        for value in obj:
            _numeric_fields(value, found)
    return found


def _percent_allowed(value: float, fact_sheet: Any) -> bool:
    """A percent must belong to a rate, a percent field, or the literal ratio. A bare 8 does not license 8%."""
    ratio = value / 100.0
    for key, number in _numeric_fields(fact_sheet):
        keyed = any(token in key.lower() for token in _PERCENT_KEY)
        if keyed and canon(number) in {canon(value), canon(ratio)}:
            return True
        if canon(number) == canon(ratio):
            return True
    return False


def _is_percent_match(text: str, match: re.Match[str]) -> bool:
    if match.group(2):
        return True
    return bool(re.match(r"\s+percent\b", text[match.end():], re.I))


def _delta(fact_sheet: Any) -> float | None:
    if not isinstance(fact_sheet, dict):
        return None
    for source in (fact_sheet, fact_sheet.get("drivers") if isinstance(fact_sheet.get("drivers"), dict) else {}):
        for key in ("total_delta", "delta"):
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _contributions(fact_sheet: Any) -> list[dict[str, Any]]:
    if not isinstance(fact_sheet, dict):
        return []
    drivers = fact_sheet.get("drivers")
    source = drivers if isinstance(drivers, dict) else fact_sheet
    rows = source.get("contributions") if isinstance(source, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("dimension_value") is not None]


def leading_contributions(fact_sheet: Any) -> list[dict[str, Any]]:
    """Contributions ranked by how much they pushed IN THE DIRECTION of the total change: when the KPI fell, the
    most negative segment is the largest contributor (integration on real Olist data: a +6527 segment was named
    "largest contribution" to a -42490 drop). The analyst's explicit "(unexplained)" row is not a segment."""
    rows = [r for r in _contributions(fact_sheet) if isinstance(r.get("delta"), (int, float)) and not isinstance(r.get("delta"), bool)
            and str(r.get("dimension_value")) != "(unexplained)"]
    drivers = fact_sheet.get("drivers") if isinstance(fact_sheet, dict) else None
    total = (drivers if isinstance(drivers, dict) else fact_sheet or {}).get("total_delta") if isinstance(fact_sheet, dict) else None
    sign = -1.0 if isinstance(total, (int, float)) and not isinstance(total, bool) and total < 0 else 1.0
    return [r for _k, _i, r in sorted(((sign * float(r["delta"]), -i, r) for i, r in enumerate(rows)), key=lambda t: (t[0], t[1]), reverse=True)]


def _direction_claim(word: str, negated: set[str]) -> str | None:
    if word in negated:
        if word in _UP:
            return "decreased"
        if word in _DOWN:
            return "increased"
        return None
    if word in _UP:
        return "increased"
    if word in _DOWN:
        return "decreased"
    return None


def _direction_wrong(claim: str, delta: float | None) -> bool:
    return delta is None or (claim == "increased" and delta <= 0) or (claim == "decreased" and delta >= 0)


def _direction_issues(prose: str, fact_sheet: Any) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    delta = _delta(fact_sheet)
    text = prose or ""
    negated: set[str] = set()
    for match in re.finditer(r"\b(?:not|never|n't)\s+(?:\w+\s+){0,2}([A-Za-zÀ-ÿ]+)", text, re.I):
        negated.add(match.group(1).lower())
    lowered = text.lower()
    for phrase, claim_up in [(phrase, True) for phrase in _UP_PHRASES] + [(phrase, False) for phrase in _DOWN_PHRASES]:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            last = phrase.split()[-1]
            claim = _direction_claim(last, negated) or ("increased" if claim_up else "decreased")
            if _direction_wrong(claim, delta):
                _remember(issues, seen, f"direction:{claim}")
    for match in _WORD.finditer(text):
        claim = _direction_claim(match.group(0).lower(), negated)
        if claim and _direction_wrong(claim, delta):
            _remember(issues, seen, f"direction:{claim}")
    return issues


def _ranking_issues(prose: str, fact_sheet: Any) -> list[str]:
    issues: list[str] = []
    ranked = leading_contributions(fact_sheet)
    winners = {str(ranked[0]["dimension_value"])} | {str(r["dimension_value"]) for r in ranked[1:] if r["delta"] == ranked[0]["delta"]} if ranked else set()
    for match in _RANK.finditer(prose or ""):
        prefix = (prose or "")[max(0, match.start() - 12) : match.start()].lower()
        if prefix.endswith(("second ", "third ", "deuxième ", "deuxieme ")):
            continue
        name = match.group(1)
        if name not in winners:
            issues.append(f"rank:{name}")
    return issues


def _sheet_text(fact_sheet: Any) -> str:
    return json.dumps(fact_sheet, ensure_ascii=False, default=str)


def _entity_issues(prose: str, fact_sheet: Any) -> list[str]:
    blob = _sheet_text(fact_sheet)
    issues: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b([A-Z]{2})\b", prose or ""):
        code = match.group(1)
        if code in _STATES and code not in blob:
            _remember(issues, seen, f"entity:{code}")
    for pattern in (_SNAKE, _NODE):
        for match in pattern.finditer(prose or ""):
            token = match.group(1)
            if token not in blob:
                _remember(issues, seen, f"entity:{token}")
    return issues


def _explicit_causes(obj: Any, found: list[str] | None = None) -> list[str]:
    """Values of cause / rule_id fields. A driver split is not a cause."""
    found = [] if found is None else found
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key) in _CAUSE_FIELDS:
                if isinstance(value, str) and value.strip():
                    found.append(value.strip())
                elif isinstance(value, list):
                    found.extend(str(item).strip() for item in value if isinstance(item, str) and str(item).strip())
            else:
                _explicit_causes(value, found)
    elif isinstance(obj, list):
        for value in obj:
            _explicit_causes(value, found)
    return found


def _cause_issues(prose: str, fact_sheet: Any) -> list[str]:
    if not _CAUSE.pattern or not _CAUSE.search(prose or ""):
        return []
    quoted = _explicit_causes(fact_sheet)
    lowered = (prose or "").lower()
    if any(value.lower() in lowered for value in quoted):
        return []
    return ["cause"]


def _number_issues(prose: str, fact_sheet: Any) -> list[str]:
    allowed = sheet_numbers(fact_sheet)
    issues: list[str] = []
    seen: set[str] = set()
    for match in _NUMBER.finditer(prose or ""):
        raw = match.group(1).replace(" ", "").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        number = canon(value)
        if _is_percent_match(prose, match):
            if not _percent_allowed(value, fact_sheet):
                _remember(issues, seen, f"{number}%")
            continue
        if number not in allowed:
            _remember(issues, seen, number)
    return issues


def unsupported_claims(prose: str, fact_sheet: Any) -> list[str]:
    """Everything the published text is not allowed to say.

    Digits, percents tied to a rate, direction versus the sign of the delta,
    who the top driver is, state and category names, causal phrases, and
    evaluative words from evaluative_words.yaml.
    """
    issues = _number_issues(prose, fact_sheet)
    seen = set(issues)
    for extra in (
        *_direction_issues(prose, fact_sheet),
        *_ranking_issues(prose, fact_sheet),
        *_entity_issues(prose, fact_sheet),
        *_cause_issues(prose, fact_sheet),
        # a listed word that is part of the logged facts (e.g. the cleaning strategy "constant") is quoted, not commentary
        *(f"evaluative:{word}" for word in evaluative_hits(prose)
          if not re.search(rf"{re.escape(word)}", _sheet_text(fact_sheet), re.I)),
    ):
        _remember(issues, seen, extra)
    return issues


def fact_check(prose: str, fact_sheet: Any) -> bool:
    return not unsupported_claims(prose, fact_sheet)


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if part.strip()]


def _labels_in(value: Any) -> list[str]:
    if isinstance(value, dict):
        labels = []
        if value.get("dimension_value") is not None:
            labels.append(str(value["dimension_value"]))
        return labels
    if not isinstance(value, str):
        return []
    labels = [match.group(0) for match in _SNAKE.finditer(value)]
    labels += [match.group(1) for match in _NODE.finditer(value)]
    if " " not in value.strip() and len(value.strip()) > 1:
        labels.append(value.strip())
    return labels


def _fact_index(fact_sheet: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []

    def add(path: str, obj: Any) -> None:
        facts.append({"id": path, "numbers": sheet_numbers(obj), "labels": _labels_in(obj)})

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            if obj.get("dimension_value") is not None and "delta" in obj:
                add(path or "contribution", obj)
                return
            for key, value in obj.items():
                walk(value, f"{path}.{key}" if path else str(key))
            return
        if isinstance(obj, list):
            for index, value in enumerate(obj):
                walk(value, f"{path}[{index}]")
            return
        if path and not isinstance(obj, bool):
            add(path, obj)

    walk(fact_sheet, "")
    return facts


def cite_sentences(prose: str, fact_sheet: Any) -> list[dict[str, Any]]:
    """Infer citations after the fact by overlapping numbers and labels.

    The model does not declare them. Two fields that share a value can both be attached, including the wrong one.
    """
    facts = _fact_index(fact_sheet)
    cited = []
    for sentence in _sentences(prose):
        numbers = {number for number, _percent in extract_numbers(sentence)}
        ids: list[str] = []
        for fact in facts:
            used_number = bool(numbers & set(fact["numbers"]))
            used_label = any(re.search(rf"\b{re.escape(label)}\b", sentence) for label in fact["labels"] if len(label) > 1)
            if (used_number or used_label) and fact["id"] not in ids:
                ids.append(fact["id"])
        cited.append({"sentence": sentence, "fact_ids": ids})
    return cited


def continuity_breaks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A handoff breaks when the next step reads a different count than this step wrote.

    A filter inside one step, which reads 100 rows and writes 90 of the same dataset, is not a break.
    The next step is continuous when it reads those 90.
    """
    ordered = [event for event in events if isinstance(event, dict) and event.get("agent") != "auditor"]
    breaks: list[dict[str, Any]] = []

    def measure(refs: Any) -> tuple[int | None, set[str]]:
        if not isinstance(refs, list) or not refs:
            return None, set()
        total = 0
        names: set[str] = set()
        for ref in refs:
            rows = ref.get("rows") if isinstance(ref, dict) else None
            if isinstance(rows, bool) or not isinstance(rows, int):
                return None, set()
            total += rows
            if ref.get("name"):
                names.add(str(ref["name"]))
        return total, names

    for previous, following in zip(ordered, ordered[1:], strict=False):
        rows_out, outs = measure(previous.get("outputs"))
        rows_in, ins = measure(following.get("inputs"))
        if rows_out is None or rows_in is None or rows_out == rows_in or not (outs & ins):
            continue
        breaks.append(
            {
                "from_step": previous.get("step"),
                "to_step": following.get("step"),
                "dataset": sorted(outs & ins)[0],
                "rows_out": rows_out,
                "rows_in": rows_in,
            }
        )
    return breaks
