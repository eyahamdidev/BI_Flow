"""Canonical order, pacing, synthetic shapes, Wilson intervals, and demo-check rules."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from app.constants import ABSTAIN
from app.demo_checks import empty_sheet_ok, store_hit_ok, unreachable_fallback_ok
from app.gate import case_rates, gate_passes, identical_frame_sets
from app.v7 import (
    RATE_EVENTS,
    canonical_names,
    extra_retry_wait,
    fallback_cause_of,
    note_response,
    offered_frames,
    pace_before_call,
    rejection_reasons,
    render_frames,
    write_v7,
)
from app.wilson import wilson_interval
from biflow_contracts.biflow_llm import LLMUnavailable

ROOT = Path(__file__).resolve().parents[3]
SHEETS = json.loads((ROOT / "services" / "auditor" / "eval" / "synthetic_sheets" / "sheets.json").read_text(encoding="utf-8"))["sheets"]


def _sheet(name: str) -> dict:
    return next(item for item in SHEETS if item["id"] == name)


def _names(item: dict) -> list[str]:
    return [frame.name for frame in offered_frames(item["fact_sheet"], item["lang"])]


def test_canonical_order_renders_frames_as_f1_through_f7():
    ordered = canonical_names(["F1", "F5", "F3", "F2"])
    assert ordered == ["F1", "F2", "F3", "F5"]
    text, claims = render_frames(["F1", "F5", "F3", "F2"], _sheet("syn07_both")["fact_sheet"], "en")
    assert [claim["frame"] for claim in claims] == ["F1", "F2", "F3", "F5"]
    assert text.index("went up") < text.index("largest contribution") < text.index("second largest")
    assert text.index("second largest") < text.index("raw.orders")


def test_f1_out_of_order_is_still_rejected():
    item = _sheet("syn07_both")
    offered = offered_frames(item["fact_sheet"], "en")
    reasons = rejection_reasons(json.dumps({"frames": ["F2", "F1", "F3", "F6"]}), offered)
    assert "F1 must be first" in reasons
    assert rejection_reasons(json.dumps({"frames": ["F1", "F6", "F3", "F2"]}), offered) == []


def test_pace_waits_when_the_previous_call_was_recent(monkeypatch):
    import app.v7 as v7

    slept: list[float] = []
    monkeypatch.setenv("BIFLOW_MIN_INTERVAL", "5")
    monkeypatch.setattr(v7.time, "sleep", lambda seconds: slept.append(seconds))
    v7._LAST_CALL_AT = 0.0
    assert pace_before_call() == 0.0
    assert slept == []
    pace_before_call()
    assert slept and slept[0] > 4


def test_a_429_is_logged_for_the_case_and_a_200_is_not():
    RATE_EVENTS.clear()
    import app.v7 as v7

    v7.HTTP_429 = 0
    v7.CURRENT_CASE = "ex12"
    note_response(200, "9")
    assert RATE_EVENTS == []
    assert v7.HTTP_429 == 0
    note_response(429, "12")
    assert RATE_EVENTS == [{"case": "ex12", "status": 429, "retry_after": 12.0}]
    assert extra_retry_wait("12") == 0.0
    assert extra_retry_wait("45") == 15.0
    assert extra_retry_wait(None) == 0.0


def test_http_429_fallback_is_labelled(monkeypatch):
    import app.v7 as v7

    v7.RATE_EVENTS.clear()
    v7.CURRENT_CASE = "ex12"
    monkeypatch.setenv("BIFLOW_MIN_INTERVAL", "0")

    def limited(*_args, **_kwargs):
        note_response(429, "2")
        raise LLMUnavailable("HTTP 429")

    monkeypatch.setattr("app.v7.chat_text", limited)
    result = write_v7(
        prompt_id="auditor.explain_kpi@v7",
        fact_sheet=_sheet("syn03_one_driver")["fact_sheet"],
        template="unused",
        lang="en",
        section="Explain",
    )
    assert result.source == "fallback"
    assert fallback_cause_of(result.source, result.warning) == "http_429"
    assert "fallback caused by HTTP 429" in (result.warning or "")


def test_a_selection_failure_is_not_labelled_as_a_rate_limit(monkeypatch):
    import app.v7 as v7

    v7.RATE_EVENTS.clear()
    monkeypatch.setenv("BIFLOW_MIN_INTERVAL", "0")

    def bad(*_args, **_kwargs):
        return json.dumps({"frames": ["NOPE"]})

    monkeypatch.setattr("app.v7.chat_text", bad)
    result = write_v7(
        prompt_id="auditor.explain_kpi@v7",
        fact_sheet=_sheet("syn03_one_driver")["fact_sheet"],
        template="unused",
        lang="en",
        section="Explain",
    )
    assert result.source == "fallback"
    assert fallback_cause_of(result.source, result.warning) == "selection"
    assert "HTTP 429" not in (result.warning or "")


def test_decrease_flat_rule_caveat_and_empty_sheets():
    decrease = _sheet("syn01_decrease")
    flat = _sheet("syn02_flat")
    rule = _sheet("syn05_rule")
    caveat = _sheet("syn06_caveat")
    empty = _sheet("syn09_empty")
    down, _claims = render_frames(["F1"], decrease["fact_sheet"], "en")
    assert "went down" in down
    assert "went up" not in down
    unchanged, _claims = render_frames(["F1"], flat["fact_sheet"], "en")
    assert "was unchanged" in unchanged
    rise, _claims = render_frames(["F1"], _sheet("syn04_three_drivers")["fact_sheet"], "en")
    assert "went up" in rise
    assert "went down" not in rise
    assert "F6" in _names(rule)
    rule_text, _claims = render_frames(["F6"], rule["fact_sheet"], "en")
    assert "late_delivery" in rule_text
    assert "F6" not in _names(decrease)
    assert "F7" in _names(caveat)
    caveat_text, _claims = render_frames(["F7"], caveat["fact_sheet"], "en")
    assert "Delivered orders only" in caveat_text
    assert "F7" not in _names(decrease)
    assert _names(empty) == []
    result = write_v7(prompt_id="auditor.explain_kpi@v7", fact_sheet={}, template="unused", lang="en", section="Explain")
    assert result.source == "abstain"
    assert result.text == ABSTAIN


def test_french_direction_rule_and_caveat_use_the_frame_text():
    down, _claims = render_frames(["F1"], _sheet("syn10_decrease_fr")["fact_sheet"], "fr")
    assert "en baisse" in down
    flat, _claims = render_frames(["F1"], _sheet("syn11_flat_fr")["fact_sheet"], "fr")
    assert "inchangé" in flat
    rule, _claims = render_frames(["F6"], _sheet("syn12_rule_fr")["fact_sheet"], "fr")
    assert "La règle enregistrée" in rule
    assert "late_delivery" in rule
    caveat, _claims = render_frames(["F7"], _sheet("syn13_caveat_fr")["fact_sheet"], "fr")
    assert "Réserve enregistrée" in caveat
    assert "Delivered orders only" in caveat


def test_synthetic_renderings_stay_inside_the_frames():
    from app.v7 import fixed_words, outside_frame

    for item in SHEETS:
        sheet = item["fact_sheet"]
        offered = offered_frames(sheet, item["lang"])
        names = [frame.name for frame in offered]
        if item["shape"] == "empty":
            assert names == []
            continue
        if item["shape"] == "rule_id" or item["shape"] == "rule_and_caveat":
            assert "F6" in names
        if item["shape"] == "caveat" or item["shape"] == "rule_and_caveat":
            assert "F7" in names
        if item["shape"] == "one_driver":
            assert "F3" not in names
        if item["shape"] == "no_lineage":
            assert "F5" not in names
        for mask in range(1, 2 ** len(names)):
            chosen_names = [names[index] for index in range(len(names)) if mask & (1 << index)]
            chosen = [frame for frame in offered if frame.name in chosen_names]
            text, _claims = render_frames(chosen_names, sheet, item["lang"])
            leftover, words = outside_frame(text, chosen, sheet, item["lang"])
            assert not any(char.isdigit() for char in leftover)
            assert words <= fixed_words(chosen, item["lang"])


def test_wilson_interval_for_19_of_20_is_wide_and_contains_the_rate():
    low, high = wilson_interval(19, 20)
    assert low < 0.95 < high
    assert high - low > 0.15
    assert round(low, 4) == 0.7639
    assert round(high, 4) == 0.9911


def test_wilson_rejects_a_count_above_n():
    with pytest.raises(ValueError):
        wilson_interval(21, 20)


def test_deadline_fallback_is_labelled_as_a_timeout(monkeypatch):
    monkeypatch.setenv("BIFLOW_MIN_INTERVAL", "0")

    def boom(*_args, **_kwargs):
        raise AssertionError("called")

    monkeypatch.setattr("app.v7.chat_text", boom)
    result = write_v7(
        prompt_id="auditor.explain_kpi@v7",
        fact_sheet=_sheet("syn02_flat")["fact_sheet"],
        template="unused",
        lang="en",
        section="Explain",
        deadline=time.monotonic() - 1,
    )
    assert result.source == "fallback"
    assert fallback_cause_of(result.source, result.warning) == "timeout"
    assert "was unchanged" in result.text


def test_gate_passes_only_when_every_run_is_clean_and_sets_ignore_order():
    clean = [{"id": "ex01", "source": "llm", "first_try_pass": True, "frames": ["F1", "F2", "F3"]}]
    other_order = [{"id": "ex01", "source": "llm", "first_try_pass": True, "frames": ["F1", "F3", "F2"]}]
    limited = [{"id": "ex01", "source": "fallback", "first_try_pass": None, "fallback_cause": "http_429", "frames": ["F1"]}]
    assert gate_passes([clean, clean, clean], expect_n=1)
    assert gate_passes([limited, limited, limited], drop_transport=True, expect_n=1) is False
    assert case_rates(limited, drop_transport=True)["n"] == 0
    mixed = clean + limited
    assert gate_passes([mixed, mixed, mixed], expect_n=2) is False
    assert gate_passes([mixed, mixed, mixed], drop_transport=True, expect_n=2)
    assert identical_frame_sets([clean, other_order, clean]) == 1
    changed = [{"id": "ex01", "source": "llm", "first_try_pass": True, "frames": ["F1", "F2"]}]
    assert identical_frame_sets([clean, changed, clean]) == 0


def test_citation_details_copy_the_sheet_and_leave_a_missing_event_blank():
    from app.citations import enrich_citations

    sheet = {
        "kpi_id": "revenue",
        "period": "2017-01",
        "compare_to": "2016-12",
        "definition": {"name": "Revenue", "unit": "BRL", "sql": "SELECT SUM(payment_value) AS value FROM fact_orders"},
        "drivers": {"total_delta": 1000, "contributions": [{"dimension_value": "SP", "delta": 1000}]},
        "lineage": {"found": True, "raw_tables": ["raw.orders"], "cleaning_rules": ["parse_dates"]},
    }
    events = [{"event_id": "evt-parse", "step": "parse_dates", "rule": "parse_dates", "inputs": [{"name": "raw.orders"}]}]
    detailed = enrich_citations(
        [{"sentence": "Revenue went up by 1000 BRL.", "frame": "F1", "fact_ids": ["kpi.name", "drivers.total_delta"]}],
        sheet,
        events,
    )
    facts = {item["fact_id"]: item for item in detailed[0]["facts"]}
    assert facts["kpi.name"]["value"] == "Revenue"
    assert facts["drivers.total_delta"]["value"] == "1000 BRL"
    assert facts["drivers.total_delta"]["sql"] == "SELECT SUM(payment_value) AS value FROM fact_orders"
    assert facts["drivers.total_delta"]["source_tables"] == ["raw.orders"]
    assert facts["drivers.total_delta"]["lineage_event"] == "evt-parse"
    missing = enrich_citations([{"sentence": "Revenue went up.", "fact_ids": ["drivers.total_delta"]}], sheet, [])
    assert missing[0]["facts"][0]["lineage_event"] is None
    unknown = enrich_citations([{"sentence": "Nothing.", "fact_ids": ["not.a.field"]}], sheet, events)
    assert unknown[0]["facts"][0]["value"] is None


def test_demo_checks_accept_a_store_hit_and_reject_a_model_call():
    hit = {"metrics": {"explanation_store": "hit", "answer": "Revenue went up by 1000 BRL."}, "llm_calls": []}
    assert store_hit_ok(hit, "Revenue went up by 1000 BRL.")
    called = {"metrics": {"explanation_store": "hit", "answer": "Revenue went up by 1000 BRL."}, "llm_calls": [{}]}
    assert store_hit_ok(called, "Revenue went up by 1000 BRL.") is False
    fallback = {"metrics": {"explanation_store": "miss", "prose_source": "fallback"}, "warnings": ["frame fallback used"]}
    assert unreachable_fallback_ok(fallback)
    silent = {"metrics": {"explanation_store": "miss", "prose_source": "fallback"}, "warnings": []}
    assert unreachable_fallback_ok(silent) is False
    empty = {"metrics": {"answer": ABSTAIN, "abstained": True, "explanation_store": "abstain"}}
    assert empty_sheet_ok(empty)
    filled = {"metrics": {"answer": "Revenue went up.", "abstained": False, "explanation_store": "miss"}}
    assert empty_sheet_ok(filled) is False
