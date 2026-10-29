from app import runner, summary
from app.main import app
from fastapi.testclient import TestClient


def test_health():
    assert TestClient(app).get("/health").json()["status"] == "ok"


def test_graph_stages_reference_known_modules():
    for s in runner.load_graph():
        assert s["module"] in runner.DEFAULT_PORTS, s
        assert s["mode"] and s["name"]


def test_langgraph_has_every_stage_and_failure_jumps_to_auditor():
    g = runner.build_graph().get_graph()
    names = [s["name"] for s in runner.load_graph()]
    assert set(names) | {runner.SUMMARY_NODE} <= set(g.nodes)
    edges = {(e.source, e.target) for e in g.edges}
    first_always = next(s["name"] for s in runner.load_graph() if s.get("always"))
    assert ("analyse", first_always) in edges          # conditional edge taken on failure
    assert ("analyse", "dashboard_config") in edges    # normal edge
    assert ("audit", runner.SUMMARY_NODE) in edges


def test_api_graph_returns_mermaid():
    assert "graph" in TestClient(app).get("/api/graph").json()["mermaid"]


FACTS = {"dataset": "olist", "run_status": "ok", "stages_total": 14, "total_seconds": 29.06,
         "modeling": {"orders_in_fact_table": 1000, "data_tests_passed": 52}}


def test_fact_check_accepts_numbers_from_facts():
    assert summary.unsupported_numbers("All 14 stages ran in 29.06 seconds; 1,000 orders and 52 tests.", FACTS) == []


def test_fact_check_rejects_invented_or_rounded_numbers():
    assert summary.unsupported_numbers("It took about 30 seconds for 1001 orders.", FACTS) == ["30", "1001"]


def _manifest(failed: bool) -> dict:
    stages = {"ingest": {"status": "ok", "seconds": 1.0, "mock": True},
              "etl": {"status": "failed" if failed else "ok", "seconds": 2.5, "mock": False,
                      "error": {"code": "INTERNAL", "message": "boom"} if failed else None}}
    return {"run_id": "r", "dataset": "olist", "status": "failed" if failed else "ok", "stages": stages,
            "warnings": [], "total_seconds": 3.5}


def test_template_fallback_mentions_failure_and_passes_its_own_fact_check():
    facts = summary.fact_sheet(_manifest(failed=True))
    text = summary.template(facts)
    assert "failed" in text and "'etl' failed: boom" in text
    assert summary.unsupported_numbers(text, facts) == []


def test_summary_without_llm_uses_template(monkeypatch):
    monkeypatch.setenv("BIFLOW_SUMMARY_LLM", "0")
    s = summary.summarize(_manifest(failed=False))
    assert s["source"] == "template" and "status ok" in s["text"]


def test_llm_deadline_stops_calls_immediately(monkeypatch):
    import time

    import pytest
    from biflow_contracts.biflow_llm import LLMUnavailable, chat_text, llm_deadline

    monkeypatch.setenv("FAKE_LLM", "0")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")              # no API-key short-cut: the deadline must do the work
    monkeypatch.setenv("LLM_BASE_URL", "http://10.255.255.1:9/v1")  # would hang until timeout if called
    t0 = time.monotonic()
    with llm_deadline(0.5), pytest.raises(LLMUnavailable, match="budget"):
        chat_text("test.deadline@v1", system="s", user="u")
    assert time.monotonic() - t0 < 1.0
