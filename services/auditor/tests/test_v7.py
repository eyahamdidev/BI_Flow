"""v7 frame selector. Each reject rule has one sentence that trips it and one that does not."""

from __future__ import annotations

import json
from pathlib import Path

from app.factcheck import fact_check
from app.handlers import explain
from app.prose import render_prompt, write_prose
from app.v7 import (
    fallback_names,
    fixed_words,
    offered_frames,
    outside_frame,
    rejection_reasons,
    render_frames,
    write_v7,
)
from biflow_contracts import RunRequest

ROOT = Path(__file__).resolve().parents[3]
SHEET = {
    "kpi_id": "revenue",
    "period": "2017-01",
    "compare_to": "2016-12",
    "definition": {
        "name": "Revenue",
        "unit": "BRL",
        "description": "Total payments received",
        "caveats": "Delivered orders only",
    },
    "drivers": {
        "total_delta": 1000,
        "contributions": [
            {"dimension_value": "SP", "delta": 600},
            {"dimension_value": "RJ", "delta": 400},
        ],
    },
    "lineage": {"found": True, "raw_tables": ["raw.orders"], "cleaning_rules": ["parse_dates"]},
    "rule_id": "late_delivery",
}
GOOD = {"frames": ["F1", "F2", "F3", "F5", "F6"]}


def _names(sheet: dict | None = None, lang: str = "en") -> list[str]:
    return [frame.name for frame in offered_frames(sheet or SHEET, lang)]


def test_unknown_frame_is_rejected_and_a_known_frame_is_kept():
    offered = offered_frames(SHEET, "en")
    assert rejection_reasons(json.dumps(GOOD), offered) == []
    reasons = rejection_reasons(json.dumps({"frames": ["F1", "F2", "NOPE"]}), offered)
    assert any(reason.startswith("unknown frame NOPE. Offered frames:") for reason in reasons)


def test_duplicate_frame_is_rejected():
    offered = offered_frames(SHEET, "en")
    assert "duplicate frame" not in rejection_reasons(json.dumps(GOOD), offered)
    assert "duplicate frame" in rejection_reasons(json.dumps({"frames": ["F1", "F2", "F2"]}), offered)


def test_f1_must_be_first_when_offered():
    offered = offered_frames(SHEET, "en")
    assert "F1 must be first" not in rejection_reasons(json.dumps(GOOD), offered)
    moved = {"frames": ["F2", "F1", "F3"]}
    assert "F1 must be first" in rejection_reasons(json.dumps(moved), offered)


def test_f3_is_required_when_offered_and_absent_without_a_second_driver():
    offered = offered_frames(SHEET, "en")
    assert "F3" in _names()
    missing = {"frames": ["F1", "F2", "F4"]}
    assert "F3 is offered and must be included" in rejection_reasons(json.dumps(missing), offered)
    one = {
        **SHEET,
        "drivers": {"total_delta": 1000, "contributions": [{"dimension_value": "SP", "delta": 1000}]},
    }
    assert "F3" not in _names(one)
    assert "F3" in fallback_names(offered)
    assert "F3" not in fallback_names(offered_frames(one, "en"))


def test_f2_and_f6_are_required_when_offered_and_optional_when_absent():
    offered = offered_frames(SHEET, "en")
    assert "F2" in _names()
    assert "F6" in _names()
    missing_top = {"frames": ["F1", "F3", "F6"]}
    assert "F2 is offered and must be included" in rejection_reasons(json.dumps(missing_top), offered)
    missing_rule = {"frames": ["F1", "F2", "F3"]}
    assert "F6 is offered and must be included" in rejection_reasons(json.dumps(missing_rule), offered)
    no_rule = {key: value for key, value in SHEET.items() if key != "rule_id"}
    assert "F6" not in _names(no_rule)
    no_driver = {key: value for key, value in SHEET.items() if key != "drivers"}
    assert "F2" not in _names(no_driver)
    assert "F2 is offered and must be included" not in rejection_reasons(
        json.dumps({"frames": ["F4", "F5", "F6"]}),
        offered_frames(no_driver, "en"),
    )


def test_a_frame_is_not_offered_when_a_required_id_is_missing():
    assert "F5" in _names()
    no_lineage = {key: value for key, value in SHEET.items() if key != "lineage"}
    assert "F5" not in _names(no_lineage)
    assert "F6" in _names()
    no_rule = {key: value for key, value in SHEET.items() if key != "rule_id"}
    assert "F6" not in _names(no_rule)


def test_english_and_french_rendering_use_the_logged_values():
    english, claims = render_frames(["F1", "F2", "F3"], SHEET, "en")
    assert "Revenue went up by 1000 BRL between 2016-12 and 2017-01." in english
    assert "The largest contribution came from SP (600 BRL)." in english
    assert "The second largest contribution came from RJ (400 BRL)." in english
    assert fact_check(english, SHEET)
    assert claims[0]["frame"] == "F1"
    assert claims[0]["fact_ids"] == ["kpi.name", "drivers.direction", "drivers.total_delta", "period.compare", "period.current"]
    french, _claims = render_frames(["F1", "F3"], SHEET, "fr")
    assert "Revenue a en hausse de 1000 BRL entre 2016-12 et 2017-01." in french
    assert "La deuxième plus grande contribution vient de RJ (400 BRL)." in french
    assert fact_check(french, SHEET)


def test_empty_sheet_abstains_without_a_model_call(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("called")

    monkeypatch.setattr("app.v7.chat_text", boom)
    result = write_v7(prompt_id="auditor.explain_kpi@v7", fact_sheet={}, template="unused", lang="en", section="Explain")
    assert result.source == "abstain"
    assert result.text == "not enough logged information"


def test_retry_feedback_includes_the_offered_list(monkeypatch):
    seen: list[str] = []

    def fake(*args, **kwargs):
        user = kwargs.get("user", args[2] if len(args) > 2 else "")
        seen.append(user)
        if len(seen) == 1:
            return json.dumps({"frames": ["NOPE"]})
        return json.dumps(GOOD)

    monkeypatch.setattr("app.v7.chat_text", fake)
    result = write_prose(
        prompt_id="auditor.explain_kpi@v7",
        fact_sheet=SHEET,
        template="unused",
        lang="en",
        section="Explain",
    )
    assert result.source == "llm"
    assert result.first_try_pass is False
    assert "Offered frames:" in seen[1]
    assert "F1" in seen[1]
    assert "1000 BRL" in result.text


def test_explanation_store_hits_and_changes_key_for_v7(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FAKE_LLM", "1")
    monkeypatch.setenv("BIFLOW_MOCK", "0")
    calls = {"n": 0}

    def fake(*_args, **_kwargs):
        calls["n"] += 1
        return json.dumps({"frames": ["F1", "F2", "F4"]})

    monkeypatch.setattr("app.v7.chat_text", fake)
    folder = tmp_path / "runs" / "run-1" / "05_insights"
    folder.mkdir(parents=True)
    drivers = [
        {
            "kpi_id": "revenue",
            "period": "2017-11",
            "compare_to": "2017-10",
            "total_delta": 12,
            "dimension": "customer_state",
            "contributions": [{"dimension_value": "SP", "delta": 12}],
        }
    ]
    (folder / "drivers.json").write_text(json.dumps(drivers), encoding="utf-8")
    defs = tmp_path / "runs" / "run-1" / "04_kpi"
    defs.mkdir(parents=True)
    (defs / "kpi_definitions.json").write_text(
        json.dumps([{"id": "revenue", "name": "Revenue", "description": "Total payments received", "unit": "BRL"}]),
        encoding="utf-8",
    )

    def once(rows: list[dict]) -> dict:
        (folder / "drivers.json").write_text(json.dumps(rows), encoding="utf-8")
        body = {
            "request_id": "req-1",
            "run_id": "run-1",
            "dataset": "olist",
            "mode": "explain",
            "options": {"offline_registry": True, "explain_kpi_version": "v7", "kpi_id": "revenue", "period": "2017-11", "compare_to": "2017-10"},
            "inputs": {
                "analyse.drivers": "runs/run-1/05_insights/drivers.json",
                "kpi_compute.kpi_definitions": "runs/run-1/04_kpi/kpi_definitions.json",
            },
        }
        return explain(RunRequest(**body))

    first = once(drivers)
    assert first["metrics"]["explanation_store"] == "miss"
    assert calls["n"] == 1
    assert first["metrics"]["prose_source"] == "llm"
    key = first["lineage_events"][0]["params"]["explanation_key"]
    second = once(drivers)
    assert second["metrics"]["explanation_store"] == "hit"
    assert second["metrics"]["answer"] == first["metrics"]["answer"]
    assert calls["n"] == 1
    drivers[0]["total_delta"] = 99
    drivers[0]["contributions"] = [{"dimension_value": "SP", "delta": 99}]
    changed = once(drivers)
    assert changed["metrics"]["explanation_store"] == "miss"
    assert calls["n"] == 2
    assert changed["lineage_events"][0]["params"]["explanation_key"] != key


def test_every_offered_combination_uses_only_frame_words_and_logged_digits():
    cases = json.loads((ROOT / "services" / "auditor" / "eval" / "explain_cases.json").read_text(encoding="utf-8"))["cases"]
    held = json.loads((ROOT / "services" / "auditor" / "eval" / "held_out_prose.json").read_text(encoding="utf-8"))
    fresh = json.loads((ROOT / "services" / "auditor" / "eval" / "held_out_fresh.json").read_text(encoding="utf-8"))
    banned = [item["prose"] for item in held["items"] if item.get("supported") is False]
    banned.extend(item["prose"] for item in fresh["items"])
    produced: set[str] = set()
    for case in cases:
        sheet = case["fact_sheet"]
        for lang in ("en", "fr"):
            offered = offered_frames(sheet, lang)
            names = [frame.name for frame in offered]
            for mask in range(1, 2 ** len(names)):
                chosen_names = [names[index] for index in range(len(names)) if mask & (1 << index)]
                chosen = [frame for frame in offered if frame.name in chosen_names]
                text, _claims = render_frames(chosen_names, sheet, lang)
                leftover, words = outside_frame(text, chosen, sheet, lang)
                assert not any(char.isdigit() for char in leftover)
                assert words <= fixed_words(chosen, lang)
                produced.add(text)
    assert not produced.intersection(banned)
    assert render_prompt(
        "auditor.explain_kpi@v7",
        section="Explain",
        language="English",
        fields="- F1: headline",
    )
