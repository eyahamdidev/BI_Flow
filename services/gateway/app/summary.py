"""Run summary (BO1's one LLM call per run). Spec rule 7: code computes, the LLM explains.

1. Build a FACT SHEET from the run manifest (numbers computed by code).
2. Ask the LLM for a paragraph using only those facts (prompt: prompts/gateway/run_summary/v1.yaml).
3. FACT-CHECK in code: every number in the text must appear in the fact sheet. Mismatch -> retry with feedback,
   max 2 attempts -> then fall back to a template paragraph (no LLM). LLM unreachable -> template too (rule 8).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

PROMPT_ID = "gateway.run_summary"
PROMPT_VERSION = 1
NUM = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)*(?:\.\d+)?")


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "prompts" / "gateway").is_dir():
            return p
    return Path.cwd()


def load_prompt(version: int = PROMPT_VERSION) -> dict[str, Any]:
    f = _repo_root() / "prompts" / "gateway" / "run_summary" / f"v{version}.yaml"
    return yaml.safe_load(f.read_text(encoding="utf-8"))


def fact_sheet(manifest: dict[str, Any]) -> dict[str, Any]:
    stages = manifest["stages"]
    counts: dict[str, int] = {}
    for st in stages.values():
        counts[st["status"]] = counts.get(st["status"], 0) + 1
    timed = {k: v["seconds"] for k, v in stages.items() if v.get("seconds") is not None}
    facts: dict[str, Any] = {
        "dataset": manifest["dataset"],
        "run_status": manifest["status"],
        "stages_total": len(stages),
        "stages_by_status": counts,
        "total_seconds": manifest.get("total_seconds"),
        "slowest_stage": max(timed, key=timed.get) if timed else None,
        "slowest_stage_seconds": max(timed.values()) if timed else None,
        "failed_stages": {k: (v.get("error") or {}).get("message", "")[:200] for k, v in stages.items() if v["status"] == "failed"},
        "stages_served_by_mocks": [k for k, v in stages.items() if v.get("mock")],
        "stages_served_by_mocks_count": sum(1 for v in stages.values() if v.get("mock")),
        "warnings_count": len(manifest.get("warnings", [])),
    }
    m = {k: v.get("metrics", {}) for k, v in stages.items()}
    if m.get("clean"):
        facts["cleaning"] = {k: m["clean"][k] for k in ("rows_dropped", "outliers_flagged", "needs_review", "silent_deletions") if k in m["clean"]}
    if m.get("etl"):
        e = m["etl"]
        facts["modeling"] = {"orders_in_fact_table": (e.get("rows") or {}).get("fact_orders"),
                             "data_tests_passed": e.get("dbt_tests_passed"), "data_tests_failed": e.get("dbt_tests_failed"),
                             "row_reconciliation_ok": e.get("reconciliation_ok")}
    return facts


def _numbers(obj: Any) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 2))
    elif isinstance(obj, str):
        out |= {_to_float(n) for n in NUM.findall(obj)}
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out |= _numbers(k) | _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _numbers(v)
    return out


def _to_float(s: str) -> float:
    s = s.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s) else s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return float("nan")


def unsupported_numbers(text: str, facts: dict[str, Any]) -> list[str]:
    """Numbers in the text that are not in the fact sheet (the fact-check, no model involved)."""
    allowed = _numbers(facts)
    return [n for n in NUM.findall(text) if _to_float(n) not in allowed]


def template(facts: dict[str, Any]) -> str:
    """No-LLM fallback: dry but always correct."""
    s = facts["stages_by_status"]
    parts = [f"Run on dataset '{facts['dataset']}' finished with status {facts['run_status']}: "
             f"{s.get('ok', 0)} of {facts['stages_total']} stages ok"
             + (f", {s['partial']} partial" if s.get("partial") else "")
             + (f", {s['failed']} failed" if s.get("failed") else "")
             + (f", {s['skipped']} skipped" if s.get("skipped") else "") + "."]
    for name, msg in facts["failed_stages"].items():
        parts.append(f"Stage '{name}' failed: {msg}.")
    if mod := facts.get("modeling"):
        parts.append(f"The fact table holds {mod['orders_in_fact_table']} orders; "
                     f"{mod['data_tests_passed']} data tests passed and {mod['data_tests_failed']} failed.")
    if facts["stages_served_by_mocks"]:
        parts.append(f"{len(facts['stages_served_by_mocks'])} stages were served by mocks.")
    if facts.get("total_seconds") is not None:
        parts.append(f"Total time: {facts['total_seconds']} s.")
    return " ".join(parts)


def summarize(manifest: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    """Returns {text, source: llm|template, facts, llm_calls, fact_check}."""
    from biflow_contracts.biflow_llm import LLMUnavailable, chat_text, drain_calls

    facts = fact_sheet(manifest)
    if os.getenv("BIFLOW_SUMMARY_LLM", "1") == "0":
        return {"text": template(facts), "source": "template", "facts": facts, "llm_calls": [], "fact_check": "skipped"}

    p = load_prompt()
    system = p["text"].format(lang={"en": "English", "fr": "French"}.get(lang, "English"), facts=json.dumps(facts, indent=1))
    user = "Write the summary paragraph now."
    attempts = []
    for attempt in range(2):
        try:
            text = chat_text(f"{PROMPT_ID}@v{p['version']}", system=system, user=user, role=p["model_role"], temperature=0.2).strip()
        except LLMUnavailable as e:
            attempts.append(f"LLM unavailable: {e}")
            break
        bad = unsupported_numbers(text, facts)
        if not bad:
            calls = [c.model_dump() for c in drain_calls()]
            return {"text": text, "source": "llm", "facts": facts, "llm_calls": calls, "fact_check": f"pass (attempt {attempt + 1})"}
        attempts.append(f"attempt {attempt + 1}: numbers not in facts {bad}")
        user = f"Your previous answer used numbers that are not in the facts: {bad}. Rewrite it using only numbers from the facts."
    calls = [c.model_dump() for c in drain_calls()]
    return {"text": template(facts), "source": "template", "facts": facts, "llm_calls": calls, "fact_check": "; ".join(attempts)}
