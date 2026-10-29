"""Turn one fact sheet into prose. The model sees the sheet, then a regex check keeps the numbers honest."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from biflow_contracts.biflow_llm import LLMUnavailable, chat_text

from .constants import WRITER_TEMPERATURE
from .factcheck import fact_check, unsupported_claims
from .fields import declared_citations, field_catalog, fill_fact_ids, valid_ids

SYSTEM = "You write plain-language explanations of business indicators for a non-technical reader."
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ProseResult:
    text: str
    source: str
    attempts: int
    first_try_pass: bool | None
    warning: str | None = None
    missing: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] | None = None
    citation_method: str = "inferred_overlap"
    claims: list[dict[str, Any]] | None = None


def prompts_root() -> Path:
    configured = os.getenv("BIFLOW_PROMPTS_DIR")
    if configured and Path(configured).is_dir():
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "prompts" / "auditor"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("prompts/auditor")


def _models_config() -> dict[str, Any]:
    configured = os.getenv("BIFLOW_CONFIG_DIR")
    path: Path | None = None
    if configured and (Path(configured) / "models.yaml").exists():
        path = Path(configured) / "models.yaml"
    else:
        for parent in [Path.cwd().resolve(), *Path.cwd().resolve().parents, *Path(__file__).resolve().parents]:
            candidate = parent / "config" / "models.yaml"
            if candidate.exists():
                path = candidate
                break
    if path is None:
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def explain_kpi_default() -> str:
    """Profile default from config/models.yaml. An option or env value still wins."""
    override = os.getenv("EXPLAIN_KPI_VERSION") or os.getenv("explain_kpi_version")
    if override:
        version = override
    else:
        profile = os.getenv("BIFLOW_PROFILE") or os.getenv("LLM_PROVIDER") or "ollama"
        chosen = (_models_config().get("profiles") or {}).get(profile) or {}
        version = str(chosen.get("explain_kpi_version") or ("v6" if profile == "api" else "v4"))
    if not str(version).startswith("v"):
        version = f"v{version}"
    return str(version)


def prompt_ref(name: str, options: dict[str, Any] | None = None, default: str = "v3") -> str:
    options = options or {}
    version = str(options.get(f"{name}_version") or options.get("prompt_version") or default)
    if not version.startswith("v"):
        version = f"v{version}"
    return f"auditor.{name}@{version}"


def render_prompt(prompt_id: str, **slots: str) -> str:
    name, version = prompt_id.split("@", 1)
    short = name.split(".", 1)[1]
    path = prompts_root() / short / f"{version}.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = str(document.get("text") or "")
    if document.get("engine") == "jinja2":
        from jinja2 import Environment

        return Environment(autoescape=False).from_string(text).render(**slots)
    for key, value in slots.items():
        text = text.replace("{" + key + "}", value)
    return text


def sentence_count(text: str) -> int:
    return len([part for part in _SENTENCE_SPLIT.split((text or "").strip()) if part.strip()])


def _language(lang: str) -> str:
    return "French" if lang == "fr" else "English"


def _facts(sheet: dict[str, Any]) -> str:
    return json.dumps(sheet, ensure_ascii=False, sort_keys=True, default=str)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def write_prose(
    *,
    prompt_id: str,
    fact_sheet: dict[str, Any],
    template: str,
    lang: str,
    section: str,
    min_sentences: int | None = None,
    max_sentences: int | None = None,
    deadline: float | None = None,
    judge: bool = False,
    temperature: float | None = None,
) -> ProseResult:
    """Ask the model up to three times. After two failed retries, publish the template."""
    if "@v7" in prompt_id:
        from .v7 import write_v7

        return write_v7(
            prompt_id=prompt_id,
            fact_sheet=fact_sheet,
            template=template,
            lang=lang,
            section=section,
            deadline=deadline,
        )
    if "@v6" in prompt_id:
        from .v6 import write_v6

        return write_v6(
            prompt_id=prompt_id,
            fact_sheet=fact_sheet,
            template=template,
            lang=lang,
            section=section,
            deadline=deadline,
        )
    template_missing = unsupported_claims(template, fact_sheet)
    if deadline is not None and time.monotonic() > deadline:
        return ProseResult(template, "template", 0, None, "timeout budget reached; template text used", template_missing)

    try:
        user = render_prompt(
            prompt_id,
            section=section,
            language=_language(lang),
            facts=_facts(fact_sheet),
            fields=field_catalog(fact_sheet),
        )
    except (OSError, yaml.YAMLError, FileNotFoundError):
        return ProseResult(template, "template", 0, None, "prompt file unavailable; template text used", template_missing)

    base_user = user
    first_try: bool | None = None
    last_missing: list[str] = []
    for attempt in range(1, 4):
        if deadline is not None and time.monotonic() > deadline:
            return ProseResult(template, "template", attempt - 1, first_try, "timeout budget reached; template text used", template_missing)
        try:
            raw = chat_text(prompt_id, SYSTEM, user, role="llm_main", temperature=WRITER_TEMPERATURE if temperature is None else temperature)
        except LLMUnavailable:
            return ProseResult(template, "template", attempt, first_try, "language model unavailable; template text used", template_missing)
        raw_prose = _strip_fences(raw)
        prose, unresolved = fill_fact_ids(raw_prose, fact_sheet)
        last_missing = list(unresolved)
        last_missing.extend(item for item in unsupported_claims(prose, fact_sheet) if item not in last_missing)
        count = sentence_count(prose)
        sentences_ok = True
        if min_sentences is not None and count < min_sentences:
            sentences_ok = False
        if max_sentences is not None and count > max_sentences:
            sentences_ok = False
        if prose and not last_missing and sentences_ok:
            warning = _judge_warning(prose, fact_sheet, judge, lang, section)
            method = "inferred_overlap"
            citations = None
            if unresolved == [] and "[" in raw_prose:
                method = "declared_field_id"
                citations = declared_citations(raw_prose, prose, fact_sheet)
            return ProseResult(
                prose,
                "llm",
                attempt,
                attempt == 1 if first_try is None else first_try,
                warning,
                [],
                citations,
                method,
            )
        if attempt == 1:
            first_try = False
        notes = []
        unknown = [item.split(":", 1)[1] for item in last_missing if item.startswith("placeholder:")]
        other = [item for item in last_missing if not item.startswith("placeholder:")]
        if unknown:
            shown = ", ".join(f"[{name}]" for name in unknown)
            notes.append("unknown id " + shown + "; valid ids: " + ", ".join(valid_ids(fact_sheet)))
        if other:
            notes.append("These claims are not supported by the fact sheet: " + ", ".join(other) + ".")
        if "@v4" in prompt_id:
            notes.append("Do not write numbers or units. Use a square-bracket field id from the list.")
        if not sentences_ok:
            notes.append("Write between three and five sentences.")
        user = base_user + "\n\nRewrite the answer. " + " ".join(notes)

    warning = "fact-check failed after 2 retries; template text used"
    if last_missing:
        warning += ". Unsupported claims: " + ", ".join(last_missing)
    if template_missing:
        warning += ". Template text also failed the fact-check"
    return ProseResult(template, "template", 3, False, warning, template_missing)


def _judge_warning(prose: str, fact_sheet: dict[str, Any], enabled: bool, lang: str, section: str) -> str | None:
    if not enabled:
        return None
    try:
        user = render_prompt(
            "auditor.fact_judge@v1",
            section=section,
            language=_language(lang),
            facts=_facts(fact_sheet),
            prose=prose,
        )
        raw = chat_text("auditor.fact_judge@v1", SYSTEM, user, role="llm_fast", temperature=0.0)
    except (LLMUnavailable, OSError, yaml.YAMLError, FileNotFoundError):
        return None
    word = raw.strip().split()[0].strip(".,:;").upper() if raw.strip() else ""
    if word == "FAIL":
        return "optional language-model judge flagged wording that the number check did not catch"
    return None


def passes(text: str, fact_sheet: dict[str, Any]) -> bool:
    return fact_check(text, fact_sheet)
