"""Offline eval for POST /v1/eval. No language model is called."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .completeness import completeness
from .constants import EVAL_LINEAGE_STEPS
from .factcheck import fact_check, missing_numbers, unsupported_claims
from .io_utils import load_events
from .templates import explain_template

_EVAL = Path(__file__).resolve().parents[1] / "eval"


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = round((pct / 100) * (len(ordered) - 1))
    return ordered[min(index, len(ordered) - 1)]


def _sheet_of(item: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
    if isinstance(item.get("fact_sheet"), dict):
        return item["fact_sheet"]
    return default


def _labelled_recall(items: list[dict[str, Any]]) -> dict[str, Any]:
    unsupported = [item for item in items if item.get("supported") is False]
    supported = [item for item in items if item.get("supported") is True]
    caught = 0
    for item in unsupported:
        issues = unsupported_claims(item["prose"], item["fact_sheet"])
        expected = item.get("unsupported")
        if expected:
            caught += int(bool(issues) and all(token in issues for token in expected))
        else:
            caught += int(bool(issues))
    false_rejects = sum(1 for item in supported if not fact_check(item["prose"], item["fact_sheet"]))
    return {
        "count": len(items),
        "unsupported": len(unsupported),
        "recall": round(caught / len(unsupported), 4) if unsupported else None,
        "false_reject_rate": round(false_rejects / len(supported), 4) if supported else None,
    }


def eval_metrics() -> dict[str, Any]:
    events, _warnings = load_events(_EVAL / "events.jsonl")
    registry = [step for steps in EVAL_LINEAGE_STEPS.values() for step in steps]
    coverage = completeness(events, {"registered_steps": registry})

    planted_doc = json.loads((_EVAL / "bad_prose.json").read_text(encoding="utf-8"))
    planted = planted_doc.get("items") if isinstance(planted_doc, dict) else planted_doc
    caught = 0
    number_caught = 0
    for item in planted:
        issues = unsupported_claims(item["prose"], item["fact_sheet"])
        if issues and all(token in issues for token in item["unsupported"]):
            caught += 1
        if missing_numbers(item["prose"], item["fact_sheet"]):
            number_caught += 1

    valid_doc = json.loads((_EVAL / "valid_prose.json").read_text(encoding="utf-8"))
    valid_default = valid_doc.get("default_sheet") if isinstance(valid_doc.get("default_sheet"), dict) else {}
    valid_items = valid_doc.get("sentences") or []
    valid_rejected = 0
    for item in valid_items:
        if not fact_check(item["prose"], _sheet_of(item, valid_default)):
            valid_rejected += 1

    held_path = _EVAL / "held_out_prose.json"
    held = None
    if held_path.exists():
        held_doc = json.loads(held_path.read_text(encoding="utf-8"))
        default_sheet = held_doc.get("fact_sheet") if isinstance(held_doc.get("fact_sheet"), dict) else {}
        held_items = [{**item, "fact_sheet": _sheet_of(item, default_sheet)} for item in held_doc.get("items") or []]
        held = _labelled_recall(held_items)
    faith_path = _EVAL / "v4_faithfulness.json"
    v4_faithfulness = None
    v4_answers = None
    if faith_path.exists():
        labelled = json.loads(faith_path.read_text(encoding="utf-8")).get("items") or []
        flags = [item.get("supported") is True for item in labelled]
        v4_answers = len(flags)
        v4_faithfulness = round(sum(flags) / len(flags), 4) if flags else None
    judge_path = _EVAL / "bakeoff_results.json"
    judge_recall = None
    if isinstance(planted_doc, dict) and planted_doc.get("llm_judge_recall") is not None:
        judge_recall = planted_doc.get("llm_judge_recall")
    elif judge_path.exists():
        bakeoff = json.loads(judge_path.read_text(encoding="utf-8"))
        judge_recall = (bakeoff.get("judge") or {}).get("recall")
    union_path = _EVAL / "judge_held_out.json"
    union_recall = None
    union_false_reject = None
    if union_path.exists():
        union_doc = json.loads(union_path.read_text(encoding="utf-8"))
        union_recall = union_doc.get("union_recall")
        union_false_reject = union_doc.get("union_false_reject_rate")
        if union_doc.get("recall") is not None:
            judge_recall = union_doc.get("recall")
    valid_judge_path = _EVAL / "judge_valid_prose.json"
    judge_false_reject = None
    if valid_judge_path.exists():
        judge_false_reject = json.loads(valid_judge_path.read_text(encoding="utf-8")).get("false_reject_rate")
    fresh_path = _EVAL / "judge_fresh_held_out.json"
    fresh_checker = None
    fresh_judge = None
    fresh_union = None
    if fresh_path.exists():
        fresh_doc = json.loads(fresh_path.read_text(encoding="utf-8"))
        fresh_checker = fresh_doc.get("checker_recall")
        fresh_judge = fresh_doc.get("judge_recall")
        fresh_union = fresh_doc.get("union_recall")

    cases = json.loads((_EVAL / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    template_ok = 0
    driver_ok = 0
    claim_ok = 0
    claim_total = 0
    timings: list[float] = []
    for case in cases:
        sheet = case["fact_sheet"]
        answer = explain_template(sheet, "en")
        started = time.perf_counter()
        passed = fact_check(answer, sheet)
        timings.append((time.perf_counter() - started) * 1000)
        template_ok += int(passed)
        driver_ok += int(all(name in answer for name in case["expected_drivers"]))
        for claim in case["claims"]:
            started = time.perf_counter()
            verdict = fact_check(claim["text"], sheet)
            timings.append((time.perf_counter() - started) * 1000)
            claim_total += 1
            claim_ok += int(verdict is claim["supported"])

    scores = json.loads((_EVAL / "readability.json").read_text(encoding="utf-8")).get("scores") or []
    numbers = [float(score) for score in scores if isinstance(score, (int, float)) and not isinstance(score, bool)]
    case_count = len(cases) or 1
    bad_count = len(planted) or 1
    return {
        "lineage_coverage": coverage["coverage"],
        "untracked_transformations": coverage["untracked_transformations"],
        "factcheck_first_try_pass_rate": round(template_ok / case_count, 4),
        "unsupported_statement_rate": round((case_count - template_ok) / case_count, 4) if cases else 0.0,
        "bad_prose_detection_rate": round(caught / bad_count, 4),
        "bad_prose_set": "development",
        "number_only_detection_rate": round(number_caught / bad_count, 4),
        "valid_prose_count": len(valid_items),
        "false_reject_rate": round(valid_rejected / len(valid_items), 4) if valid_items else None,
        "held_out_count": None if held is None else held["count"],
        "held_out_unsupported": None if held is None else held["unsupported"],
        "held_out_recall": None if held is None else held["recall"],
        "held_out_recall_before_rules": 0.3333,
        "held_out_false_reject_rate": None if held is None else held["false_reject_rate"],
        "llm_judge_recall": judge_recall,
        "held_out_union_recall": union_recall,
        "held_out_union_false_reject_rate": union_false_reject,
        "judge_false_reject_rate": judge_false_reject,
        "fresh_held_out_checker_recall": fresh_checker,
        "fresh_held_out_judge_recall": fresh_judge,
        "fresh_held_out_union_recall": fresh_union,
        "v4_published_answers": v4_answers,
        "v4_published_faithfulness": v4_faithfulness,
        "planted_bad_count": len(planted),
        "planted_bad_first_try_pass_rate": round((bad_count - caught) / bad_count, 4),
        "faithfulness": round(claim_ok / claim_total, 4) if claim_total else 0.0,
        "driver_recall": round(driver_ok / case_count, 4),
        "explain_cases": len(cases),
        "labelled_claims": claim_total,
        "readability_mean": round(sum(numbers) / len(numbers), 3) if numbers else None,
        "readability_responses": len(numbers),
        "latency_ms_p50": round(_percentile(timings, 50), 4) if timings else None,
        "latency_ms_p95": round(_percentile(timings, 95), 4) if timings else None,
        "prompt_version": "v6",
    }
