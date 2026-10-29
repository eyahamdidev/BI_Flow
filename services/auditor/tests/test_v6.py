"""v6 fact-id JSON pipeline. Each new reject rule has a sentence that trips it and the good answer does not."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.factcheck import fact_check, unsupported_claims
from app.prose import explain_kpi_default, prompt_ref, render_prompt, write_prose
from app.redact import redact
from app.v6 import direction_word, rejection_reasons, v6_id_list, write_v6

SHEET = {
    "kpi_id": "revenue",
    "period": "2017-01",
    "compare_to": "2016-12",
    "definition": {"name": "Revenue", "unit": "BRL", "description": "Total payments received"},
    "drivers": {
        "total_delta": 1000,
        "compare_to": "2016-12",
        "contributions": [
            {"dimension_value": "SP", "delta": 600},
            {"dimension_value": "RJ", "delta": 400},
        ],
    },
}

GOOD = {
    "sentences": [
        {
            "text": "The indicator [kpi.name] is logged for [period.current] against [period.compare].",
            "ids": ["kpi.name", "period.current", "period.compare"],
        },
        {
            "text": "The logged change [drivers.direction] by [drivers.total_delta].",
            "ids": ["drivers.direction", "drivers.total_delta"],
        },
        {
            "text": "The largest contribution came from [drivers.top1.label] at [drivers.top1.delta].",
            "ids": ["drivers.top1.label", "drivers.top1.delta"],
        },
    ]
}


def _raw(sentences: list[dict]) -> str:
    return json.dumps({"sentences": sentences})


def _with(text: str, ids: list[str], index: int = 0) -> str:
    sentences = [dict(item) for item in GOOD["sentences"]]
    sentences[index] = {"text": text, "ids": ids}
    return _raw(sentences)


def test_direction_word_follows_the_sign_in_both_languages():
    assert direction_word(1000, "en") == "went up"
    assert direction_word(-5, "en") == "went down"
    assert direction_word(1000, "fr") == "en hausse"
    assert direction_word(-5, "fr") == "en baisse"
    assert direction_word(0, "en") == "was unchanged"


def test_valid_ids_include_the_label_and_skip_an_empty_sheet():
    assert v6_id_list(SHEET)[:5] == ["kpi.name", "period.current", "period.compare", "drivers.direction", "drivers.total_delta"]
    assert "drivers.top1.label" in v6_id_list(SHEET)
    assert "drivers.top2.delta" in v6_id_list(SHEET)
    assert v6_id_list({}) == []


def test_good_json_renders_the_logged_unit_and_passes():
    from app.v6 import render_accepted

    assert rejection_reasons(json.dumps(GOOD), SHEET, "en") == []
    prose, claims = render_accepted(json.dumps(GOOD), SHEET, "en")
    assert "1000 BRL" in prose
    assert "600 BRL" in prose
    assert "went up" in prose
    assert "SP" in prose
    assert "units" not in prose
    assert fact_check(prose, SHEET)
    assert claims[2]["ids"] == ["drivers.top1.label", "drivers.top1.delta"]


def test_evaluative_word_outside_an_id_is_rejected():
    sheet = {"total_delta": 12}
    assert fact_check("The logged change is 12.", sheet)
    assert fact_check("The logged change is 12 for [note.important].", sheet)
    rejected = unsupported_claims("Revenue is an important KPI and the change is 12.", sheet)
    assert "evaluative:important" in rejected
    assert not fact_check("Revenue is an important KPI and the change is 12.", sheet)
    assert "evaluative:critique" in unsupported_claims("Le changement de 12 est critique.", sheet)


def test_required_ids_must_appear():
    assert rejection_reasons(json.dumps(GOOD), SHEET, "en") == []
    dropped = _with("The next contribution came from [drivers.top2.label].", ["drivers.top2.label"], index=2)
    assert "missing required id: drivers.top1.label" in rejection_reasons(dropped, SHEET, "en")


def test_each_v6_rule_rejects_one_sentence(monkeypatch):
    unknown = _with("See [SC] and [kpi.name].", ["SC", "kpi.name"])
    assert any(reason.startswith("unknown id [SC]. Valid ids:") for reason in rejection_reasons(unknown, SHEET, "en"))
    assert "drivers.top1.label" in " ".join(rejection_reasons(unknown, SHEET, "en"))

    no_id = _with("The indicator is logged.", [])
    assert "sentence has no id" in rejection_reasons(no_id, SHEET, "en")

    mismatch = _with("The indicator [kpi.name] is logged.", ["period.current"])
    assert "ids list does not match the bracket ids in the text" in rejection_reasons(mismatch, SHEET, "en")

    digit = _with("The indicator [kpi.name] moved 9.", ["kpi.name"])
    assert "digit outside brackets" in rejection_reasons(digit, SHEET, "en")

    forbidden = _with("The indicator [kpi.name] rose because of a promotion.", ["kpi.name"])
    reasons = " ".join(rejection_reasons(forbidden, SHEET, "en"))
    assert "forbidden word: rose" in reasons
    assert "forbidden word: because" in reasons

    wrong_top = _with(
        "The largest contribution came from [drivers.top2.label].",
        ["drivers.top2.label"],
        index=2,
    )
    assert any("rank:RJ" in reason for reason in rejection_reasons(wrong_top, SHEET, "en"))

    seen: list[str] = []

    def fake(*args, **kwargs):
        user = kwargs.get("user", args[2] if len(args) > 2 else "")
        seen.append(user)
        if len(seen) == 1:
            return unknown
        return json.dumps(GOOD)

    monkeypatch.setattr("app.v6.chat_text", fake)
    result = write_prose(
        prompt_id="auditor.explain_kpi@v6",
        fact_sheet=SHEET,
        template="The logged change is 1000 BRL.",
        lang="en",
        section="Explain",
    )
    assert result.source == "llm"
    assert result.first_try_pass is False
    assert "1000 BRL" in result.text
    assert "unknown id [SC]. Valid ids:" in seen[1]
    assert "drivers.top1.label" in seen[1]


def test_both_retries_publish_the_template(monkeypatch):
    monkeypatch.setattr("app.v6.chat_text", lambda *_args, **_kwargs: "not json")
    result = write_prose(
        prompt_id="auditor.explain_kpi@v6",
        fact_sheet=SHEET,
        template="The logged change is 1000 BRL.",
        lang="en",
        section="Explain",
    )
    assert result.source == "template"
    assert result.attempts == 3
    assert result.text == "The logged change is 1000 BRL."
    assert result.warning is not None
    assert "template text used" in result.warning


def test_empty_sheet_abstains_without_a_model_call(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("called")

    monkeypatch.setattr("app.v6.chat_text", boom)
    result = write_v6(prompt_id="auditor.explain_kpi@v6", fact_sheet={}, template="fallback", lang="en", section="Explain")
    assert result.source == "abstain"
    assert result.text == "not enough logged information"


def test_explain_version_follows_the_profile(monkeypatch):
    monkeypatch.delenv("EXPLAIN_KPI_VERSION", raising=False)
    monkeypatch.delenv("explain_kpi_version", raising=False)
    monkeypatch.setenv("BIFLOW_PROFILE", "api")
    assert explain_kpi_default() == "v8"
    monkeypatch.setenv("BIFLOW_PROFILE", "ollama")
    assert explain_kpi_default() == "v8"
    monkeypatch.setenv("BIFLOW_PROFILE", "low_ram")
    assert explain_kpi_default() == "v8"
    monkeypatch.setenv("explain_kpi_version", "v3")
    assert explain_kpi_default() == "v3"
    assert prompt_ref("explain_kpi", {"explain_kpi_version": "v6"}, default="v4") == "auditor.explain_kpi@v6"


def test_v6_prompt_is_jinja_and_shows_a_label_example():
    assert prompt_ref("explain_kpi", {"explain_kpi_version": "v6"}) == "auditor.explain_kpi@v6"
    rendered = render_prompt(
        "auditor.explain_kpi@v6",
        section="Explain revenue",
        language="English",
        fields="- drivers.top1.label\n- kpi.name",
        facts="{}",
    )
    assert "Explain revenue" in rendered
    assert "drivers.top1.label" in rendered
    assert "[drivers.top1.label]" in rendered
    assert "went up" not in rendered
    assert "{" in rendered


def test_a_key_never_appears_in_logs_or_eval_files():
    sample = "gsk_" + "exampleSecret123"
    assert "gsk_" not in redact("Authorization: Bearer " + sample)
    assert "[redacted]" in redact("LLM_API_KEY=" + sample)
    root = Path(__file__).resolve().parents[3]
    pattern = re.compile(r"gsk_[A-Za-z0-9]+")
    offenders: list[str] = []
    for folder in (root / "services" / "auditor", root / "prompts" / "auditor"):
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".json", ".md", ".yaml", ".yml", ".csv", ".txt", ".log"}:
                continue
            if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path))
    assert offenders == []
