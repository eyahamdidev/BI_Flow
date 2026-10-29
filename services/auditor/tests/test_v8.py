"""v8. The model keeps facts and writes the paragraph. Python only rejects a mismatch with the log."""

from __future__ import annotations

import json

from app.prose import write_prose
from app.v8 import analyst_facts, rejection_reasons, write_v8

SHEET = {
    "kpi_id": "revenue",
    "period": "2017-01",
    "compare_to": "2016-12",
    "definition": {
        "name": "Revenue",
        "description": "Total payments received for delivered orders",
        "unit": "BRL",
    },
    "drivers": {
        "total_delta": 1000,
        "contributions": [
            {"dimension_value": "SP", "delta": 600},
            {"dimension_value": "RJ", "delta": 400},
            {"dimension_value": "MG", "delta": 50},
        ],
    },
    "lineage": {"found": True, "raw_tables": ["raw.orders"], "cleaning_rules": ["parse_dates"]},
}

KEPT = [
    "kpi.name",
    "period.current",
    "period.compare",
    "drivers.total_delta",
    "drivers.contributions[0]",
]
DROPPED = [
    "definition.description",
    "drivers.contributions[1]",
    "drivers.contributions[2]",
    "lineage.raw_tables",
    "lineage.cleaning_rules",
]
EXPLANATION = (
    "Revenue went up by 1000 BRL between 2016-12 and 2017-01. "
    "The largest contribution came from SP (600 BRL). "
    "The logged change for Revenue is 1000."
)


def _reply(kept: list[str], dropped: list[str], explanation: str) -> str:
    return json.dumps({"kept": kept, "dropped": dropped, "explanation": explanation})


def test_the_model_text_is_published_and_the_choice_is_kept(monkeypatch):
    monkeypatch.setattr("app.v8.chat_text", lambda *_args, **_kwargs: _reply(KEPT, DROPPED, EXPLANATION))
    result = write_v8(
        prompt_id="auditor.explain_kpi@v8",
        fact_sheet=SHEET,
        template="python backup",
        lang="en",
        section="Explain",
    )
    assert result.source == "llm"
    assert result.text == EXPLANATION
    assert result.first_try_pass is True
    assert [item["id"] for item in result.choice["kept"]] == KEPT
    assert any(item["value"].startswith("MG") for item in result.choice["dropped"])
    assert "python backup" not in result.text


def test_an_invented_number_is_sent_back_and_the_rewrite_is_published(monkeypatch):
    replies = iter(
        [
            _reply(KEPT, DROPPED, "Revenue went up by 999999 BRL between 2016-12 and 2017-01. SP contributed 600. The change is 1000."),
            _reply(KEPT, DROPPED, EXPLANATION),
        ]
    )
    monkeypatch.setattr("app.v8.chat_text", lambda *_args, **_kwargs: next(replies))
    result = write_v8(
        prompt_id="auditor.explain_kpi@v8",
        fact_sheet=SHEET,
        template="python backup",
        lang="en",
        section="Explain",
    )
    assert result.source == "llm"
    assert result.attempts == 2
    assert result.first_try_pass is False
    assert result.text == EXPLANATION
    assert "999999" not in result.text


def test_mentioning_a_dropped_contributor_is_rejected():
    raw = _reply(
        KEPT,
        DROPPED,
        "Revenue went up by 1000 BRL between 2016-12 and 2017-01. The largest contribution came from SP (600 BRL). MG added 50.",
    )
    reasons = rejection_reasons(raw, SHEET)
    assert any("dropped fact drivers.contributions[2]" in reason for reason in reasons)


def test_a_short_sheet_still_calls_the_model(monkeypatch):
    small = {
        "kpi_id": "orders",
        "period": "2017-02",
        "definition": {"name": "Orders"},
        "drivers": {"total_delta": 4, "contributions": []},
    }
    facts = analyst_facts(small)
    assert len(facts) < 5
    explanation = "Orders for 2017-02 changed by 4. The logged change is 4. Orders is the logged name."
    monkeypatch.setattr(
        "app.v8.chat_text",
        lambda *_args, **_kwargs: _reply([fact.id for fact in facts], [], explanation),
    )
    result = write_prose(
        prompt_id="auditor.explain_kpi@v8",
        fact_sheet=small,
        template="python backup",
        lang="en",
        section="Explain",
    )
    assert result.source == "llm"
    assert result.text == explanation
    assert result.choice["dropped"] == []


def test_an_empty_sheet_does_not_call_the_model(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("called")

    monkeypatch.setattr("app.v8.chat_text", boom)
    result = write_v8(prompt_id="auditor.explain_kpi@v8", fact_sheet={}, template="backup", lang="en", section="Explain")
    assert result.source == "abstain"
    assert result.text == "not enough logged information"
