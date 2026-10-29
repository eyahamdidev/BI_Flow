"""v7 explain pipeline. The model selects frame names. Code writes the sentences."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import yaml
from biflow_contracts.biflow_llm import LLMUnavailable, chat_text
from pydantic import BaseModel, ConfigDict, ValidationError

from .constants import ABSTAIN
from .factcheck import evaluative_hits, unsupported_claims
from .fields import format_field
from .prose import ProseResult, _language, _strip_fences, render_prompt
from .redact import redact
from .v6 import _delta, _ranked_drivers, direction_word

_FIELD = re.compile(r"\[([A-Za-z_][A-Za-z0-9_.]*)\]")
_WORD = re.compile(r"[A-Za-zÀ-ÿ']+")
_DIGIT = re.compile(r"\d")
_SYSTEM = "You reply with one JSON object and no other text."
_FALLBACK_ORDER = ("F1", "F2", "F3", "F5", "F6")
_REQUIRED_WHEN_OFFERED = ("F1", "F2", "F3", "F6")
FRAME_ORDER = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
MIN_INTERVAL_S = 8.0
RETRY_AFTER_CAP_S = 30.0
HTTP_429 = 0
RATE_EVENTS: list[dict[str, Any]] = []
CURRENT_CASE: str | None = None
_LAST_CALL_AT = 0.0
_EFFORT_OK: bool | None = None


class Frame:
    def __init__(self, name: str, meaning: str, requires: list[str], text_en: str, text_fr: str) -> None:
        self.name = name
        self.meaning = meaning
        self.requires = requires
        self.text_en = text_en
        self.text_fr = text_fr

    def text(self, lang: str) -> str:
        return self.text_fr if lang == "fr" else self.text_en


class V7Doc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    frames: list[str] | None = None
    abstain: bool | None = None


def _load_frames() -> dict[str, Frame]:
    path = Path(__file__).with_name("frames.yaml")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    frames: dict[str, Frame] = {}
    for name, body in (loaded.get("frames") or {}).items():
        if not isinstance(body, dict):
            continue
        frames[str(name)] = Frame(
            name=str(name),
            meaning=str(body.get("meaning") or ""),
            requires=[str(item) for item in body.get("requires") or []],
            text_en=str(body.get("text_en") or ""),
            text_fr=str(body.get("text_fr") or ""),
        )
    return frames


_FRAMES = _load_frames()


def min_interval() -> float:
    """Eight seconds on the api provider. BIFLOW_MIN_INTERVAL overrides that, including 0 for tests."""
    raw = os.getenv("BIFLOW_MIN_INTERVAL")
    if raw is not None and str(raw).strip():
        try:
            return float(raw)
        except ValueError:
            return MIN_INTERVAL_S
    if os.getenv("LLM_PROVIDER") == "api":
        return MIN_INTERVAL_S
    return 0.0


def canonical_names(names: list[str]) -> list[str]:
    """Published sentences always run F1..F7. Validation still sees the model's order."""
    rank = {name: index for index, name in enumerate(FRAME_ORDER)}
    return sorted(names, key=lambda name: (rank.get(name, len(FRAME_ORDER)), name))


def retry_after_seconds(header: str | None, default: float | None = None) -> float | None:
    if header is None or not str(header).strip():
        return default
    try:
        return float(header)
    except ValueError:
        return default


def extra_retry_wait(header: str | None, cap: float = RETRY_AFTER_CAP_S) -> float:
    """Seconds still to wait so the full Retry-After is honoured above the client's 30s cap."""
    seconds = retry_after_seconds(header, None)
    if seconds is None:
        return 0.0
    return max(0.0, seconds - cap)


def note_response(status: int, retry_after: str | None) -> None:
    global HTTP_429
    if status != 429:
        return
    HTTP_429 += 1
    RATE_EVENTS.append(
        {
            "case": CURRENT_CASE,
            "status": 429,
            "retry_after": retry_after_seconds(retry_after, None),
        }
    )


def pace_before_call() -> float:
    """Sleep so the next model call starts at least min_interval seconds after the previous one."""
    global _LAST_CALL_AT
    gap_needed = min_interval()
    now = time.monotonic()
    waited = 0.0
    if _LAST_CALL_AT and gap_needed > 0:
        remaining = gap_needed - (now - _LAST_CALL_AT)
        if remaining > 0:
            time.sleep(remaining)
            waited = remaining
    _LAST_CALL_AT = time.monotonic()
    return waited


def fallback_cause_of(source: str, warning: str | None) -> str | None:
    if source != "fallback":
        return None
    text = warning or ""
    if "HTTP 429" in text:
        return "http_429"
    if "timeout" in text.lower():
        return "timeout"
    if "unavailable" in text.lower():
        return "unavailable"
    return "selection"


def _nonempty(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, (list, tuple)):
        return any(_nonempty(item) for item in value)
    return False


def _first_rule_id(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "rule_id" and isinstance(value, str) and value.strip():
                return value.strip()
            found = _first_rule_id(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _first_rule_id(value)
            if found:
                return found
    return None


def frame_values(sheet: dict[str, Any], lang: str) -> dict[str, Any]:
    """Logged values a frame may use. An empty value is omitted, so its frame is not offered."""
    values: dict[str, Any] = {}
    definition = sheet.get("definition") if isinstance(sheet.get("definition"), dict) else {}
    name = (definition or {}).get("name") or sheet.get("kpi_id")
    if isinstance(name, str) and name.strip():
        values["kpi.name"] = name.strip()
    description = (definition or {}).get("description")
    if _nonempty(description):
        values["definition.description"] = description
    caveats = (definition or {}).get("caveats")
    if _nonempty(caveats):
        values["definition.caveats"] = caveats
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
    lineage = sheet.get("lineage") if isinstance(sheet.get("lineage"), dict) else {}
    tables = lineage.get("raw_tables") if isinstance(lineage, dict) else None
    rules = lineage.get("cleaning_rules") if isinstance(lineage, dict) else None
    if _nonempty(tables):
        values["lineage.raw_tables"] = tables
    if _nonempty(rules):
        values["lineage.cleaning_rules"] = rules
    rule = _first_rule_id(sheet)
    if rule:
        values["rule_id"] = rule
    return values


def offered_frames(sheet: dict[str, Any], lang: str) -> list[Frame]:
    values = frame_values(sheet, lang)
    chosen: list[Frame] = []
    for frame in _FRAMES.values():
        if frame.requires and all(_nonempty(values.get(name)) for name in frame.requires):
            chosen.append(frame)
    return chosen


def _render_frame(frame: Frame, values: dict[str, Any], sheet: dict[str, Any], lang: str) -> str:
    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        value = values.get(path)
        if path == "drivers.direction":
            return str(value)
        rendered = format_field(value, path, sheet)
        return str(rendered) if rendered is not None else match.group(0)

    return _FIELD.sub(replace, frame.text(lang))


def render_frames(names: list[str], sheet: dict[str, Any], lang: str) -> tuple[str, list[dict[str, Any]]]:
    values = frame_values(sheet, lang)
    parts: list[str] = []
    claims: list[dict[str, Any]] = []
    for name in canonical_names(names):
        frame = _FRAMES[name]
        sentence = _render_frame(frame, values, sheet, lang)
        parts.append(sentence)
        claims.append({"frame": name, "sentence": sentence, "fact_ids": list(frame.requires), "rendered": sentence})
    return " ".join(parts), claims


def fallback_names(offered: list[Frame]) -> list[str]:
    available = {frame.name for frame in offered}
    return [name for name in _FALLBACK_ORDER if name in available]


def parse_v7(raw: str) -> tuple[V7Doc | None, str | None]:
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
        return V7Doc.model_validate(payload), None
    except ValidationError:
        return None, 'response does not match {"frames":["F1"]}'


def rejection_reasons(raw: str, offered: list[Frame]) -> list[str]:
    names = [frame.name for frame in offered]
    if not names:
        doc, error = parse_v7(raw)
        if error or doc is None:
            return [error or "response is not valid JSON"]
        if doc.abstain:
            return []
        return ["abstain is the only valid answer when no frame is offered"]
    doc, error = parse_v7(raw)
    if error or doc is None:
        return [error or "response is not valid JSON"]
    if doc.abstain:
        return ["abstain is only valid when no frame is offered"]
    selected = [str(name) for name in (doc.frames or [])]
    if not selected:
        return ["response has no frames"]
    reasons: list[str] = []
    if len(selected) != len(set(selected)):
        reasons.append("duplicate frame")
    unknown = [name for name in selected if name not in names]
    for name in unknown:
        reasons.append(f"unknown frame {name}. Offered frames: {', '.join(names)}")
    if "F1" in names and selected[0] != "F1":
        reasons.append("F1 must be first")
    for name in _REQUIRED_WHEN_OFFERED:
        if name in names and name not in selected:
            reasons.append(f"{name} is offered and must be included")
    if len(names) >= 3 and not 3 <= len(selected) <= 5:
        reasons.append("select between 3 and 5 frames")
    if len(names) < 3 and set(selected) != set(names):
        reasons.append("fewer than 3 frames are offered; return every offered frame")
    if len(selected) > 5:
        reasons.append("select at most 5 frames")
    return list(dict.fromkeys(reasons))


def secondary_findings(text: str, sheet: dict[str, Any]) -> list[str]:
    """Checker and evaluative list, recorded when they reject code-rendered frame text."""
    findings: list[str] = []
    for issue in unsupported_claims(text, sheet):
        findings.append(f"checker:{issue}")
    for word in evaluative_hits(text):
        findings.append(f"evaluative:{word}")
    return findings


def fixed_words(frames: list[Frame], lang: str) -> set[str]:
    words: set[str] = set()
    for frame in frames:
        words.update(word.lower() for word in _WORD.findall(_FIELD.sub(" ", frame.text(lang))))
    return words


def outside_frame(rendered: str, frames: list[Frame], sheet: dict[str, Any], lang: str) -> tuple[str, set[str]]:
    """Text left after the substituted values are removed, and the words in that leftover."""
    values = frame_values(sheet, lang)
    leftover = rendered
    formatted = []
    for frame in frames:
        for name in frame.requires:
            value = values.get(name)
            shown = str(value) if name == "drivers.direction" else format_field(value, name, sheet)
            if shown:
                formatted.append(str(shown))
    for shown in sorted(set(formatted), key=len, reverse=True):
        leftover = leftover.replace(shown, " ")
    return leftover, {word.lower() for word in _WORD.findall(leftover)}


def _note(reasons: list[str], offered: list[Frame]) -> str:
    names = ", ".join(frame.name for frame in offered) or "none"
    detail = " ".join(reasons)
    return f"The previous answer was rejected. {detail} Offered frames: {names}"


def _result(text: str, source: str, attempts: int, first_try: bool | None, warning: str | None, claims: list[dict[str, Any]]) -> ProseResult:
    citations = [{"sentence": claim["sentence"], "fact_ids": claim["fact_ids"], "frame": claim["frame"]} for claim in claims]
    return ProseResult(text, source, attempts, first_try, warning, [], citations, "declared_field_id", claims)


def _complete(prompt_id: str, user: str) -> str:
    """Seed is already 7 in the shared client. reasoning_effort=low is added for the api provider."""
    global _EFFORT_OK
    pace_before_call()
    if os.getenv("LLM_PROVIDER") != "api" or _EFFORT_OK is False:
        return chat_text(prompt_id, _SYSTEM, user, role="llm_main", temperature=0.0)
    import biflow_contracts.biflow_llm as llm

    original = llm.httpx.post

    def wrapped(url, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and "messages" in payload:
            payload = dict(payload)
            payload["seed"] = 7
            payload["reasoning_effort"] = "low"
            kwargs["json"] = payload
        response = original(url, **kwargs)
        status = getattr(response, "status_code", None)
        if status == 429:
            headers = getattr(response, "headers", {}) or {}
            header = headers.get("Retry-After")
            note_response(429, None if header is None else str(header))
            extra = extra_retry_wait(None if header is None else str(header))
            if extra > 0:
                time.sleep(extra)
        return response

    llm.httpx.post = wrapped
    try:
        return chat_text(prompt_id, _SYSTEM, user, role="llm_main", temperature=0.0)
    except ValueError:
        _EFFORT_OK = False
        llm.httpx.post = original
        return chat_text(prompt_id, _SYSTEM, user, role="llm_main", temperature=0.0)
    finally:
        llm.httpx.post = original


def write_v7(
    *,
    prompt_id: str,
    fact_sheet: dict[str, Any],
    template: str,
    lang: str,
    section: str,
    deadline: float | None = None,
) -> ProseResult:
    """Up to two retries. The published fallback is the fixed frame list, with a warning."""
    del template
    offered = offered_frames(fact_sheet, lang)
    if not offered:
        return ProseResult(ABSTAIN, "abstain", 0, None, None, [], [{"sentence": ABSTAIN, "fact_ids": []}], "declared_field_id")
    try:
        catalogue = "\n".join(f"- {frame.name}: {frame.meaning}" for frame in offered)
        base_user = render_prompt(prompt_id, section=section, language=_language(lang), fields=catalogue)
    except (OSError, FileNotFoundError):
        names = fallback_names(offered)
        text, claims = render_frames(names, fact_sheet, lang)
        return _result(text, "fallback", 0, None, redact("prompt file unavailable; frame fallback used"), claims)

    user = base_user
    first_try: bool | None = None
    last_reasons: list[str] = []
    for attempt in range(1, 4):
        if deadline is not None and time.monotonic() > deadline:
            names = fallback_names(offered)
            text, claims = render_frames(names, fact_sheet, lang)
            warning = "fallback caused by timeout. timeout budget reached; frame fallback used"
            return _result(text, "fallback", attempt - 1, first_try, redact(warning), claims)
        seen_rates = len(RATE_EVENTS)
        try:
            raw = _complete(prompt_id, user)
        except LLMUnavailable as exc:
            names = fallback_names(offered)
            text, claims = render_frames(names, fact_sheet, lang)
            detail = f"language model unavailable; frame fallback used ({exc})"
            if len(RATE_EVENTS) > seen_rates:
                detail = "fallback caused by HTTP 429. " + detail
            elif "timeout" in str(exc).lower():
                detail = "fallback caused by timeout. " + detail
            return _result(text, "fallback", attempt, first_try, redact(detail), claims)
        last_reasons = rejection_reasons(raw, offered)
        if not last_reasons:
            doc, _error = parse_v7(raw)
            selected = [str(name) for name in (doc.frames or [])]
            text, claims = render_frames(selected, fact_sheet, lang)
            findings = secondary_findings(text, fact_sheet)
            if findings:
                names = fallback_names(offered)
                text, claims = render_frames(names, fact_sheet, lang)
                again = secondary_findings(text, fact_sheet)
                warning = "secondary check rejected the rendered frames; frame fallback used. " + ", ".join(findings)
                if again:
                    warning += ". Fallback rendering also flagged: " + ", ".join(again)
                return _result(text, "fallback", attempt, False, redact(warning), claims)
            passed = attempt == 1 if first_try is None else first_try
            return _result(text, "llm", attempt, passed, None, claims)
        if attempt == 1:
            first_try = False
        user = base_user + "\n\n" + _note(last_reasons, offered)
    names = fallback_names(offered)
    text, claims = render_frames(names, fact_sheet, lang)
    warning = "frame selection failed after 2 retries; frame fallback used"
    if last_reasons:
        warning += ". " + " ".join(last_reasons)
    return _result(text, "fallback", 3, False, redact(warning), claims)
