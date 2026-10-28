"""v6 explain pipeline. The model returns JSON fact ids. Code fills values and checks the prose."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from biflow_contracts.biflow_llm import LLMUnavailable, chat_text
from pydantic import BaseModel, ConfigDict, ValidationError

from .constants import ABSTAIN
from .factcheck import evaluative_hits, unsupported_claims
from .fields import format_field
from .prose import ProseResult, _facts, _language, _strip_fences, render_prompt
from .redact import redact

_FIELD = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)\]")
_DIGIT = re.compile(r"\d")
_STATES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}
_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "janvier", "février", "fevrier", "mars", "avril",
    "mai", "juin", "juillet", "août", "aout", "septembre", "octobre", "novembre", "décembre", "decembre",
)
_ADVICE = ("should", "recommend", "suggest", "ought", "il faut", "veuillez")
_EXTRA_CAUSE = (
    "as a result", "hence", "parce que", "à cause de", "a cause de", "en raison de",
    "grâce à", "grace a", "donc", "par conséquent", "par consequent",
)
_SYSTEM = "You reply with one JSON object and no other text."


class V6Sentence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str
    ids: list[str]


class V6Doc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sentences: list[V6Sentence] | None = None
    abstain: bool | None = None


def direction_word(delta: float, lang: str) -> str:
    """The word code inserts for [drivers.direction]. The model does not choose it."""
    if lang == "fr":
        if delta > 0:
            return "en hausse"
        if delta < 0:
            return "en baisse"
        return "inchangé"
    if delta > 0:
        return "went up"
    if delta < 0:
        return "went down"
    return "was unchanged"


def _ranked_drivers(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    drivers = sheet.get("drivers") if isinstance(sheet.get("drivers"), dict) else {}
    rows = drivers.get("contributions") if isinstance(drivers, dict) else None
    scored: list[tuple[float, int, dict[str, Any]]] = []
    if isinstance(rows, list):
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            delta = row.get("delta")
            if isinstance(delta, bool) or not isinstance(delta, (int, float)):
                continue
            if row.get("dimension_value") is None:
                continue
            scored.append((float(delta), -index, row))
    scored.sort(reverse=True)
    return [row for _delta, _index, row in scored[:3]]


def _delta(sheet: dict[str, Any]) -> float | None:
    drivers = sheet.get("drivers") if isinstance(sheet.get("drivers"), dict) else {}
    value = drivers.get("total_delta") if isinstance(drivers, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def v6_values(sheet: dict[str, Any], lang: str) -> dict[str, Any]:
    """The only ids v6 may fill, in prompt order."""
    values: dict[str, Any] = {}
    definition = sheet.get("definition") if isinstance(sheet.get("definition"), dict) else {}
    name = (definition or {}).get("name") or sheet.get("kpi_id")
    if isinstance(name, str) and name.strip():
        values["kpi.name"] = name.strip()
    period = sheet.get("period")
    if isinstance(period, str) and period.strip():
        values["period.current"] = period.strip()
    drivers = sheet.get("drivers") if isinstance(sheet.get("drivers"), dict) else {}
    compare = sheet.get("compare_to") or (drivers.get("compare_to") if isinstance(drivers, dict) else None)
    if isinstance(compare, str) and compare.strip():
        values["period.compare"] = compare.strip()
    delta = _delta(sheet)
    if delta is not None:
        values["drivers.direction"] = direction_word(delta, lang)
        values["drivers.total_delta"] = delta
    for rank, row in enumerate(_ranked_drivers(sheet), start=1):
        values[f"drivers.top{rank}.label"] = row.get("dimension_value")
        values[f"drivers.top{rank}.delta"] = row.get("delta")
    return values


def v6_id_list(sheet: dict[str, Any], lang: str = "en") -> list[str]:
    return list(v6_values(sheet, lang))


def _outside(text: str) -> str:
    return _FIELD.sub(" ", text or "")


def _forbidden_lexicon() -> list[str]:
    from .factcheck import _DOWN, _DOWN_PHRASES, _LEX, _UP, _UP_PHRASES

    phrases = set(_UP) | set(_DOWN) | set(_UP_PHRASES) | set(_DOWN_PHRASES) | set(_ADVICE) | set(_EXTRA_CAUSE) | set(_MONTHS)
    phrases.update(str(item).lower() for item in (_LEX.get("cause_connectives") or []))
    phrases.add("%")
    phrases.update({"brl", "usd", "eur", "r$", "$", "percent", "percentage"})
    return sorted((phrase for phrase in phrases if phrase), key=len, reverse=True)


def _forbidden_hits(text: str) -> list[str]:
    outside = _outside(text)
    lowered = outside.lower()
    hits: list[str] = []
    for phrase in _forbidden_lexicon():
        if phrase in {"%", "$", "r$"}:
            if phrase in lowered and phrase not in hits:
                hits.append(phrase)
            continue
        if re.search(rf"\b{re.escape(phrase)}\b", lowered) and phrase not in hits:
            hits.append(phrase)
    for match in re.finditer(r"\b([A-Z]{2})\b", outside):
        code = match.group(1)
        if code in _STATES and code not in hits:
            hits.append(code)
    return hits


def _known_labels(sheet: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    definition = sheet.get("definition") if isinstance(sheet.get("definition"), dict) else {}
    for value in ((definition or {}).get("name"), sheet.get("kpi_id")):
        if isinstance(value, str) and len(value.strip()) > 2:
            labels.append(value.strip())
    for row in _ranked_drivers(sheet):
        label = row.get("dimension_value")
        if isinstance(label, str) and len(label.strip()) > 2 and label.strip().upper() not in _STATES:
            labels.append(label.strip())
    return labels


def parse_v6(raw: str) -> tuple[V6Doc | None, str | None]:
    stripped = _strip_fences(raw or "")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None, "response is not valid JSON"
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None, "response is not valid JSON"
    if not isinstance(payload, dict):
        return None, "response is not a JSON object"
    try:
        return V6Doc.model_validate(payload), None
    except ValidationError:
        return None, "response does not match {sentences:[{text, ids}]}"


def rejection_reasons(raw: str, sheet: dict[str, Any], lang: str) -> list[str]:
    """Reasons to refuse the model text before it is published. Empty means it rendered cleanly."""
    allowed = v6_values(sheet, lang)
    if not allowed:
        return ["no valid ids"]
    doc, error = parse_v6(raw)
    if error or doc is None:
        return [error or "response is not valid JSON"]
    if doc.abstain:
        return ["abstain is only valid when the fact sheet has no ids"]
    sentences = doc.sentences or []
    if not 3 <= len(sentences) <= 5:
        return ["write between 3 and 5 sentences"]
    reasons: list[str] = []
    rendered_parts: list[str] = []
    for sentence in sentences:
        found = _FIELD.findall(sentence.text or "")
        if not sentence.ids or not found:
            reasons.append("sentence has no id")
            continue
        if list(sentence.ids) != found:
            reasons.append("ids list does not match the bracket ids in the text")
        unknown = [name for name in found if name not in allowed]
        for name in unknown:
            reasons.append(f"unknown id [{name}]. Valid ids: {', '.join(allowed)}")
        if _DIGIT.search(_outside(sentence.text or "")):
            reasons.append("digit outside brackets")
        hits = _forbidden_hits(sentence.text or "")
        for label in _known_labels(sheet):
            if re.search(rf"\b{re.escape(label)}\b", _outside(sentence.text or ""), re.I):
                hits.append(label)
        for hit in hits:
            reasons.append(f"forbidden word: {hit}")
        for word in evaluative_hits(sentence.text or ""):
            reasons.append(f"forbidden word: {word}")
        if unknown or not found:
            continue
        filled, missing = _fill_sentence(sentence.text, allowed, sheet)
        if missing:
            for name in missing:
                reasons.append(f"unknown id [{name}]. Valid ids: {', '.join(allowed)}")
            continue
        rendered_parts.append(filled)
    missing_required: list[str] = []
    used: set[str] = set()
    for sentence in sentences:
        used.update(str(name) for name in (sentence.ids or []))
        used.update(_FIELD.findall(sentence.text or ""))
    for name in ("kpi.name", "drivers.direction", "drivers.total_delta"):
        if name not in used:
            missing_required.append(f"missing required id: {name}")
    if "drivers.top.label" not in used and "drivers.top1.label" not in used:
        missing_required.append("missing required id: drivers.top1.label")
    if not reasons:
        issues = unsupported_claims(" ".join(rendered_parts), sheet)
        if issues:
            reasons.append("These claims are not supported by the fact sheet: " + ", ".join(issues) + ".")
    reasons.extend(missing_required)
    if reasons:
        return list(dict.fromkeys(reasons))
    return []


def _fill_sentence(text: str, allowed: dict[str, Any], sheet: dict[str, Any]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        if path not in allowed:
            missing.append(path)
            return match.group(0)
        value = allowed[path]
        rendered = value if path == "drivers.direction" else format_field(value, path, sheet)
        if rendered is None:
            missing.append(path)
            return match.group(0)
        return str(rendered)

    return _FIELD.sub(replace, text or ""), missing


def render_accepted(raw: str, sheet: dict[str, Any], lang: str) -> tuple[str, list[dict[str, Any]]]:
    doc, _error = parse_v6(raw)
    allowed = v6_values(sheet, lang)
    claims: list[dict[str, Any]] = []
    parts: list[str] = []
    for sentence in doc.sentences or []:
        filled, _missing = _fill_sentence(sentence.text, allowed, sheet)
        claims.append({"sentence": sentence.text, "rendered": filled, "ids": list(sentence.ids)})
        parts.append(filled)
    return " ".join(parts), claims


def write_v6(
    *,
    prompt_id: str,
    fact_sheet: dict[str, Any],
    template: str,
    lang: str,
    section: str,
    deadline: float | None = None,
) -> ProseResult:
    """Up to two retries. The published fallback is the template, with a warning."""
    allowed = v6_values(fact_sheet, lang)
    if not allowed:
        return ProseResult(ABSTAIN, "abstain", 0, None, None, [], [{"sentence": ABSTAIN, "fact_ids": []}], "declared_field_id")
    try:
        base_user = render_prompt(
            prompt_id,
            section=section,
            language=_language(lang),
            fields="\n".join(f"- {name}" for name in allowed),
            facts=_facts(fact_sheet),
        )
    except (OSError, FileNotFoundError):
        return ProseResult(template, "template", 0, None, redact("prompt file unavailable; template text used"))

    user = base_user
    first_try: bool | None = None
    last_reasons: list[str] = []
    for attempt in range(1, 4):
        if deadline is not None and time.monotonic() > deadline:
            return ProseResult(template, "template", attempt - 1, first_try, redact("timeout budget reached; template text used"))
        try:
            raw = chat_text(prompt_id, _SYSTEM, user, role="llm_main", temperature=0.0)
        except LLMUnavailable as exc:
            return ProseResult(template, "template", attempt, first_try, redact(f"language model unavailable; template text used ({exc})"))
        last_reasons = rejection_reasons(raw, fact_sheet, lang)
        if not last_reasons:
            prose, claims = render_accepted(raw, fact_sheet, lang)
            citations = [{"sentence": claim["rendered"], "fact_ids": claim["ids"]} for claim in claims]
            return ProseResult(
                prose,
                "llm",
                attempt,
                attempt == 1 if first_try is None else first_try,
                None,
                [],
                citations,
                "declared_field_id",
                claims,
            )
        if attempt == 1:
            first_try = False
        user = base_user + "\n\nThe previous answer was rejected. " + " ".join(last_reasons)
    warning = "fact-check failed after 2 retries; template text used"
    if last_reasons:
        warning += ". " + " ".join(last_reasons)
    return ProseResult(template, "template", 3, False, redact(warning))
