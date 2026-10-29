"""v8 explain pipeline. The model sees every logged fact, chooses which to keep, and writes the paragraph."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from biflow_contracts.biflow_llm import LLMUnavailable, chat_text
from pydantic import BaseModel, ConfigDict, ValidationError

from .constants import ABSTAIN
from .factcheck import evaluative_hits, unsupported_claims
from .factsheet import sheet_is_empty
from .prose import ProseResult, _language, _strip_fences, render_prompt, sentence_count
from .redact import redact
from .v7 import _first_rule_id

KEEP_LIMIT = 5
_SYSTEM = (
    "You are the analyst. You read the logged facts, decide which ones the reader needs, "
    "and write the explanation. Reply with one JSON object and no other text."
)
@dataclass(frozen=True)
class Fact:
    id: str
    shown: str
    say: tuple[str, ...] = ()
    hide: tuple[str, ...] = ()


class V8Doc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kept: list[str] | None = None
    dropped: list[str] | None = None
    explanation: str | None = None
    abstain: bool | None = None


def _add(rows: list[Fact], fact_id: str, shown: Any, say: tuple[str, ...] = (), hide: tuple[str, ...] = ()) -> None:
    if shown is None or shown == "" or shown == []:
        return
    if isinstance(shown, list):
        text = ", ".join(str(item) for item in shown if item not in (None, ""))
    else:
        text = str(shown).strip()
    if not text:
        return
    rows.append(Fact(fact_id, text, say, hide))


def analyst_facts(sheet: dict[str, Any]) -> list[Fact]:
    """Every speakable fact on the sheet, in file order. Contributions are not pre-ranked."""
    if not isinstance(sheet, dict) or sheet_is_empty(sheet):
        return []
    definition = sheet.get("definition") if isinstance(sheet.get("definition"), dict) else {}
    drivers = sheet.get("drivers") if isinstance(sheet.get("drivers"), dict) else {}
    lineage = sheet.get("lineage") if isinstance(sheet.get("lineage"), dict) else {}
    rows: list[Fact] = []
    name = (definition or {}).get("name") or sheet.get("kpi_id")
    _add(rows, "kpi.name", name, (str(name).strip(),) if isinstance(name, str) and name.strip() else ())
    _add(rows, "period.current", sheet.get("period"), (str(sheet.get("period")).strip(),) if sheet.get("period") else ())
    compare = sheet.get("compare_to") or (drivers or {}).get("compare_to")
    _add(rows, "period.compare", compare, (str(compare).strip(),) if isinstance(compare, str) and compare.strip() else ())
    description = (definition or {}).get("description")
    description_text = str(description).strip() if isinstance(description, str) else ""
    _add(rows, "definition.description", description, (description_text,) if description_text else ())
    unit = (definition or {}).get("unit")
    grain = (definition or {}).get("grain")
    grain_text = str(grain).strip() if isinstance(grain, str) else ""
    _add(rows, "definition.grain", grain, (grain_text,) if grain_text else (), (grain_text,) if grain_text else ())
    caveat = (definition or {}).get("caveats")
    caveat_text = str(caveat).strip() if isinstance(caveat, str) else ""
    _add(rows, "definition.caveats", caveat, (caveat_text,) if caveat_text else (), (caveat_text,) if caveat_text else ())
    delta = (drivers or {}).get("total_delta")
    if isinstance(delta, (int, float)) and not isinstance(delta, bool):
        shown = f"{delta} {unit}".strip() if isinstance(unit, str) and unit.strip() else str(delta)
        _add(rows, "drivers.total_delta", shown, (str(delta),))
    contributions = (drivers or {}).get("contributions") if isinstance(drivers, dict) else None
    if isinstance(contributions, list):
        for index, item in enumerate(contributions):
            if not isinstance(item, dict) or item.get("dimension_value") is None or item.get("delta") is None:
                continue
            label = str(item.get("dimension_value")).strip()
            shown = f"{label} {item.get('delta')}"
            if isinstance(unit, str) and unit.strip():
                shown = f"{shown} {unit.strip()}"
            _add(rows, f"drivers.contributions[{index}]", shown, (label,), (label,))
    tables = [str(item) for item in ((lineage or {}).get("raw_tables") or []) if isinstance(item, str) and item.strip()]
    _add(rows, "lineage.raw_tables", tables, tuple(tables), tuple(tables))
    rules = [str(item) for item in ((lineage or {}).get("cleaning_rules") or []) if isinstance(item, str) and item.strip()]
    _add(rows, "lineage.cleaning_rules", rules, tuple(rules), tuple(rules))
    rule_id = _first_rule_id(sheet)
    _add(rows, "rule_id", rule_id, (rule_id,) if rule_id else (), (rule_id,) if rule_id else ())
    return rows


def fact_catalog(facts: list[Fact]) -> str:
    return "\n".join(f"- {fact.id} = {fact.shown}" for fact in facts)


def parse_v8(raw: str) -> tuple[V8Doc | None, str | None]:
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
        return V8Doc.model_validate(payload), None
    except ValidationError:
        return None, 'response does not match {"kept":[],"dropped":[],"explanation":"..."}'


def _present(text: str, token: str) -> bool:
    if not token:
        return True
    if re.fullmatch(r"-?\d+(?:\.\d+)?", token):
        return token in text or token.lstrip("-") in text
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", text) is not None


def rejection_reasons(raw: str, sheet: dict[str, Any]) -> list[str]:
    facts = analyst_facts(sheet)
    if not facts:
        doc, error = parse_v8(raw)
        if error or doc is None:
            return [error or "response is not valid JSON"]
        if doc.abstain:
            return []
        return ["abstain is the only valid answer when no fact is logged"]
    doc, error = parse_v8(raw)
    if error or doc is None:
        return [error or "response is not valid JSON"]
    if doc.abstain:
        return ["abstain is only valid when no fact is logged"]
    known = {fact.id: fact for fact in facts}
    kept = [str(item) for item in (doc.kept or [])]
    dropped = [str(item) for item in (doc.dropped or [])]
    reasons: list[str] = []
    if len(kept) != len(set(kept)) or len(dropped) != len(set(dropped)):
        reasons.append("duplicate fact id")
    unknown = [item for item in kept + dropped if item not in known]
    for item in unknown:
        reasons.append(f"unknown fact {item}")
    missing = [fact.id for fact in facts if fact.id not in set(kept) | set(dropped)]
    if missing:
        reasons.append("you did not classify: " + ", ".join(missing))
    overlap = sorted(set(kept) & set(dropped))
    if overlap:
        reasons.append("listed as both kept and dropped: " + ", ".join(overlap))
    limit = min(KEEP_LIMIT, len(facts))
    if len(facts) > KEEP_LIMIT and len(kept) != KEEP_LIMIT:
        reasons.append(f"keep exactly {KEEP_LIMIT} facts")
    if len(facts) <= KEEP_LIMIT and set(kept) != set(known):
        reasons.append("five or fewer facts are logged; keep every fact")
    explanation = str(doc.explanation or "").strip()
    if not explanation:
        reasons.append("explanation is empty")
    else:
        minimum = 3 if len(facts) >= 3 else 1
        count = sentence_count(explanation)
        if count < minimum or count > KEEP_LIMIT:
            reasons.append(f"write {minimum} to {KEEP_LIMIT} sentences")
        for fact_id in kept:
            fact = known.get(fact_id)
            if fact is None:
                continue
            for token in fact.say:
                if not _present(explanation, token):
                    reasons.append(f"kept fact {fact_id} is missing from the explanation")
                    break
        for fact_id in dropped:
            fact = known.get(fact_id)
            if fact is None:
                continue
            for token in fact.hide:
                if token and _present(explanation, token):
                    reasons.append(f"dropped fact {fact_id} appears in the explanation")
                    break
        for word in evaluative_hits(explanation):
            reasons.append(f"forbidden word: {word}")
        grain_kept = "definition.grain" in kept
        if not grain_kept and re.search(r"\b(monthly|daily|weekly|mensuel|mensuelle|quotidien|hebdomadaire)\b", explanation, re.I):
            reasons.append("time grain was not logged")
        if len(kept) == limit and not unknown and not missing:
            issues = unsupported_claims(explanation, sheet)
            for issue in issues:
                reasons.append(f"unsupported: {issue}")
    return list(dict.fromkeys(reasons))


def _choice(doc: V8Doc, facts: list[Fact]) -> dict[str, Any]:
    known = {fact.id: fact for fact in facts}
    kept = [str(item) for item in (doc.kept or [])]
    dropped = [str(item) for item in (doc.dropped or [])]

    def pack(ids: list[str]) -> list[dict[str, str]]:
        return [{"id": fact_id, "value": known[fact_id].shown} for fact_id in ids if fact_id in known]

    return {"kept": pack(kept), "dropped": pack(dropped)}


def write_v8(
    *,
    prompt_id: str,
    fact_sheet: dict[str, Any],
    template: str,
    lang: str,
    section: str,
    deadline: float | None = None,
) -> ProseResult:
    """The published paragraph is the model's text. Python rejects a choice the log does not support."""
    facts = analyst_facts(fact_sheet)
    if not facts:
        return ProseResult(ABSTAIN, "abstain", 0, None, None, [], [{"sentence": ABSTAIN, "fact_ids": []}], "declared_field_id")
    try:
        base_user = render_prompt(
            prompt_id,
            section=section,
            language=_language(lang),
            fields=fact_catalog(facts),
            keep=str(min(KEEP_LIMIT, len(facts))),
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
        last_reasons = rejection_reasons(raw, fact_sheet)
        if not last_reasons:
            doc, _error = parse_v8(raw)
            assert doc is not None
            explanation = str(doc.explanation or "").strip()
            choice = _choice(doc, facts)
            citations = [
                {
                    "sentence": explanation,
                    "fact_ids": [item["id"] for item in choice["kept"]],
                }
            ]
            return ProseResult(
                explanation,
                "llm",
                attempt,
                attempt == 1 if first_try is None else first_try,
                None,
                [],
                citations,
                "declared_field_id",
                [{"sentence": explanation, "fact_ids": citations[0]["fact_ids"]}],
                choice,
            )
        if attempt == 1:
            first_try = False
        user = base_user + "\n\nThe previous answer was rejected. " + " ".join(last_reasons)
    warning = "fact-check failed after 2 retries; template text used"
    if last_reasons:
        warning += ". " + " ".join(last_reasons)
    return ProseResult(template, "template", 3, False, redact(warning))
