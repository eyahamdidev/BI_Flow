"""Behaviour tests for the auditor. Contract coverage stays in test_contract.py."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from app.completeness import completeness
from app.constants import STATIC_LINEAGE_STEPS
from app.eval_runner import eval_metrics
from app.factcheck import cite_sentences, continuity_breaks, fact_check, missing_numbers, unsupported_claims
from app.factsheet import select_drivers
from app.fields import fill_fact_ids, format_field, lookup
from app.graph_builder import build_lineage_graph, upstream
from app.handlers import audit, explain, graph
from app.io_utils import find_input
from app.prose import write_prose
from app.templates import completeness_template
from biflow_contracts import RunRequest

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "lineage_graph.schema.json").read_text(encoding="utf-8"))


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FAKE_LLM", "1")
    monkeypatch.setenv("BIFLOW_MOCK", "0")
    return tmp_path


def _req(mode: str, run_id: str = "run-1", **kwargs) -> RunRequest:
    body = {"request_id": "req-1", "run_id": run_id, "dataset": "olist", "mode": mode, "options": {"offline_registry": True}}
    if "options" in kwargs:
        body["options"] = {**body["options"], **kwargs.pop("options")}
    body.update(kwargs)
    return RunRequest(**body)


def _event(agent: str, step: str, **extra) -> dict:
    return {
        "event_id": f"{agent}-{step}",
        "run_id": "run-1",
        "ts": "2026-01-01T00:00:00Z",
        "agent": agent,
        "step": step,
        "inputs": extra.pop("inputs", []),
        "outputs": extra.pop("outputs", []),
        "rule": extra.pop("rule", step),
        "method": extra.pop("method", "deterministic"),
        "params": extra.pop("params", {}),
        **extra,
    }


def _write_events(root: Path, run_id: str, events: list[dict]) -> Path:
    path = root / "runs" / run_id / "lineage" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return path


def _all_steps() -> list[dict]:
    events = []
    for agent, steps in STATIC_LINEAGE_STEPS.items():
        for step in steps:
            events.append(_event(agent, step, rule=step))
    return events


def test_factcheck_accepts_only_logged_numbers():
    sheet = {"total_delta": 12, "rows_out": 1234, "share": 0.08, "period": "2018-03", "note": "k=5"}
    assert fact_check("The logged change is 12 and 1,234 rows remain.", sheet)
    assert fact_check("That is 8%.", sheet)
    assert missing_numbers("It rose 8% and then 7.", sheet) == ["7"]
    assert missing_numbers("A drop of 1500 rows.", sheet) == ["1500"]
    assert "2019" in missing_numbers("This happened in 2019.", sheet)
    assert fact_check("Review score i1 stayed logged.", sheet)
    assert fact_check("Model qwen2.5 was not a logged figure.", sheet)
    assert missing_numbers("The change was -4.", {"total_delta": 4}) == ["-4"]


@pytest.mark.parametrize(
    ("prose", "sheet", "ok", "issue"),
    [
        ("That is 8%.", {"share": 0.08}, True, "8%"),
        ("That is 8%.", {"orders": 8}, False, "8%"),
        ("Revenue went up by 12.", {"total_delta": 12}, True, "direction:increased"),
        ("Revenue went up.", {"total_delta": -12}, False, "direction:increased"),
        ("Le revenu est en hausse.", {"total_delta": 12}, True, "direction:increased"),
        ("Le revenu est en baisse.", {"total_delta": 12}, False, "direction:decreased"),
        (
            "The largest contribution came from the state of SP.",
            {"drivers": {"total_delta": 12, "contributions": [{"dimension_value": "SP", "delta": 9}, {"dimension_value": "RJ", "delta": 3}]}},
            True,
            "rank:the",
        ),
        (
            "The largest contribution came from RJ.",
            {"drivers": {"total_delta": 12, "contributions": [{"dimension_value": "SP", "delta": 9}, {"dimension_value": "RJ", "delta": 3}]}},
            False,
            "rank:RJ",
        ),
        ("Orders moved in SP.", {"drivers": {"contributions": [{"dimension_value": "SP", "delta": 9}]}}, True, "entity:MG"),
        ("Orders moved in MG.", {"drivers": {"contributions": [{"dimension_value": "SP", "delta": 9}]}}, False, "entity:MG"),
        ("The change was caused by late_delivery.", {"rule_id": "late_delivery", "total_delta": 12}, True, "cause"),
        ("The change was caused by carrier delays.", {"carrier": "delays", "total_delta": 12}, False, "cause"),
    ],
)
def test_each_rule_accepts_one_sentence_and_rejects_one(prose, sheet, ok, issue):
    assert fact_check(prose, sheet) is ok
    assert (issue in unsupported_claims(prose, sheet)) is (not ok)


def test_fact_id_fill_writes_the_logged_unit_and_keeps_the_rank_check(monkeypatch):
    sheet = {
        "definition": {"unit": "BRL", "name": "Revenue"},
        "period": "2017-01",
        "share": 0.08,
        "drivers": {
            "total_delta": 1000,
            "contributions": [
                {"dimension_value": "SP", "delta": 600},
                {"dimension_value": "RJ", "delta": 400},
            ],
        },
    }
    assert format_field(1000, "drivers.total_delta", sheet) == "1000 BRL"
    assert format_field(0.08, "share", sheet) == "8%"
    filled, missing = fill_fact_ids("The logged change is [drivers.total_delta].", sheet)
    assert missing == []
    assert filled == "The logged change is 1000 BRL."
    assert fact_check(filled, sheet)
    wrong, _missing = fill_fact_ids(
        "The largest contribution came from [drivers.contributions[1].dimension_value].",
        sheet,
    )
    assert wrong.endswith("RJ.")
    assert not fact_check(wrong, sheet)
    _kept, unknown = fill_fact_ids("See [drivers.nope].", sheet)
    assert unknown == ["placeholder:drivers.nope"]

    monkeypatch.setattr("app.prose.chat_text", lambda *_args, **_kwargs: "The logged change is [drivers.total_delta].")
    result = write_prose(
        prompt_id="auditor.explain_kpi@v4",
        fact_sheet=sheet,
        template="The logged change is 1000 BRL.",
        lang="en",
        section="Explain",
        min_sentences=1,
        max_sentences=5,
    )
    assert result.source == "llm"
    assert result.text == "The logged change is 1000 BRL."
    assert "units" not in result.text
    assert result.citation_method == "declared_field_id"
    assert result.citations[0]["fact_ids"] == ["drivers.total_delta"]
    assert lookup(sheet, "drivers.top.label") == "SP"
    assert format_field(600, "drivers.top.delta", sheet) == "600 BRL"
    labelled, label_missing = fill_fact_ids("The largest contribution came from [drivers.top.label].", sheet)
    assert label_missing == []
    assert labelled == "The largest contribution came from SP."
    assert fact_check(labelled, sheet)


def test_unknown_field_id_retry_names_the_valid_ids(monkeypatch):
    seen: list[str] = []
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        user = kwargs.get("user", args[2] if len(args) > 2 else "")
        seen.append(user)
        if calls["n"] == 1:
            return "See [SC]."
        return "The largest contribution came from [drivers.top.label]."

    monkeypatch.setattr("app.prose.chat_text", fake)
    sheet = {
        "definition": {"unit": "BRL"},
        "drivers": {
            "total_delta": 1000,
            "contributions": [
                {"dimension_value": "SP", "delta": 600},
                {"dimension_value": "RJ", "delta": 400},
            ],
        },
    }
    result = write_prose(
        prompt_id="auditor.explain_kpi@v4",
        fact_sheet=sheet,
        template="The logged change is 1000 BRL.",
        lang="en",
        section="Explain",
        min_sentences=1,
        max_sentences=5,
    )
    assert result.source == "llm"
    assert result.text == "The largest contribution came from SP."
    assert "unknown id [SC]" in seen[1]
    assert "valid ids:" in seen[1]
    assert "drivers.top.label" in seen[1]
    assert "drivers.total_delta" in seen[1]


def test_extended_checker_keeps_supported_wording_and_rejects_the_rest():
    sheet = {
        "total_delta": 12,
        "share": 0.08,
        "drivers": {
            "total_delta": 1000,
            "contributions": [
                {"dimension_value": "SP", "delta": 600},
                {"dimension_value": "RJ", "delta": 400},
            ],
        },
    }
    assert fact_check("That is 8%.", {"share": 0.08})
    assert fact_check("Revenue increased by 12.", {"total_delta": 12})
    assert fact_check("Revenue did not increase.", {"total_delta": -12})
    assert fact_check("The largest logged contribution is SP at 600.", sheet)
    assert fact_check("Orders moved in SP.", sheet)
    assert "8%" in unsupported_claims("Revenue rose 8%.", {"orders": 8})
    assert missing_numbers("Revenue rose 8%.", {"orders": 8}) == []
    assert "direction:increased" in unsupported_claims("Revenue increased.", {"total_delta": -12})
    assert "direction:decreased" in unsupported_claims("Revenue fell.", {"total_delta": 12})
    assert "rank:RJ" in unsupported_claims("The largest contribution is RJ.", sheet)
    assert "entity:MG" in unsupported_claims("Orders moved in MG.", sheet)
    assert "entity:health_beauty" in unsupported_claims("The category health_beauty explains it.", sheet)
    assert "cause" in unsupported_claims("The change was caused by a carrier strike.", {"total_delta": 12})


def test_citations_and_row_continuity():
    sheet = {"period": "2017-11", "drivers": {"total_delta": 12, "contributions": [{"dimension_value": "SP", "delta": 12}]}}
    cited = cite_sentences("Compared with the previous period, the logged change is 12. The logged contribution is SP.", sheet)
    assert any("total_delta" in fact_id for row in cited for fact_id in row["fact_ids"])
    assert any("SP" == row["sentence"][-2:] or any(fact_id.startswith("drivers.contributions") for fact_id in row["fact_ids"]) for row in cited)
    events = [
        _event("ingest_quality", "ingest_csv", outputs=[{"name": "orders", "rows": 100}]),
        _event("profile_clean", "profile_tables", inputs=[{"name": "orders", "rows": 90}]),
        _event("etl", "dbt_staging", inputs=[{"name": "orders", "rows": 90}], outputs=[{"name": "orders", "rows": 90}]),
    ]
    breaks = continuity_breaks(events)
    assert breaks == [{"from_step": "ingest_csv", "to_step": "profile_tables", "dataset": "orders", "rows_out": 100, "rows_in": 90}]
    filtered = [
        _event("ingest_quality", "ingest_csv", outputs=[{"name": "orders", "rows": 100}]),
        _event(
            "profile_clean",
            "impute_product_weight",
            inputs=[{"name": "orders", "rows": 100}],
            outputs=[{"name": "orders", "rows": 90}],
        ),
        _event("etl", "dbt_staging", inputs=[{"name": "orders", "rows": 90}]),
    ]
    assert continuity_breaks(filtered) == []


def test_static_registry_matches_other_modules():
    for module, expected in STATIC_LINEAGE_STEPS.items():
        tree = ast.parse((ROOT / "services" / module / "app" / "main.py").read_text(encoding="utf-8"))
        assigns = {t.id: n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "lineage_steps":
                value = assigns.get(node.value.id, node.value) if isinstance(node.value, ast.Name) else node.value
                if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "sorted":  # e.g. sorted({...})
                    found = sorted(ast.literal_eval(value.args[0]))
                else:
                    found = ast.literal_eval(value)
        assert found == expected, module


def test_upstream_follows_raw_clean_dbt_and_sql():
    events = [
        _event(
            "profile_clean",
            "parse_dates",
            rule="parse_dates(order_purchase_timestamp)",
            inputs=[{"name": "orders", "path": "runs/run-1/00_ingest/orders.parquet", "rows": 100}],
            outputs=[{"name": "orders", "path": "runs/run-1/02_clean/orders.parquet", "rows": 100}],
        ),
        _event(
            "etl",
            "dbt_marts",
            rule="dbt run --select marts",
            inputs=[{"name": "orders", "path": "runs/run-1/02_clean/orders.parquet", "rows": 100}],
            outputs=[{"name": "fact_orders", "path": "runs/run-1/03_etl/fact_orders", "rows": 100}],
        ),
        _event(
            "semantic_kpi",
            "compute_kpi",
            rule="SELECT SUM(payment_value) AS value FROM fact_orders",
            params={"kpi_id": "revenue", "sql": "SELECT SUM(payment_value) AS value FROM fact_orders"},
            inputs=[{"name": "fact_orders", "path": "runs/run-1/03_etl/fact_orders", "rows": 100}],
            outputs=[{"name": "kpi_values", "path": "runs/run-1/04_kpi/kpi_values.parquet", "rows": 12}],
        ),
    ]
    payload = build_lineage_graph(events)
    jsonschema.validate(payload, SCHEMA)
    path = upstream(payload, "revenue")
    assert path["found"] is True
    assert path["raw_tables"] == ["raw.orders"]
    assert path["cleaning_rules"] == ["parse_dates(order_purchase_timestamp)"]
    assert "dbt.fact_orders" in path["dbt_models"]
    assert path["kpi_sql"].startswith("SELECT SUM")
    assert path["paths"][0]["nodes"] == ["raw.orders", "clean.orders", "dbt.fact_orders", "kpi.revenue"]
    for node in payload["nodes"]:
        assert {"id", "label", "layer"} <= set(node)
    for edge in payload["edges"]:
        assert {"from", "to", "step"} <= set(edge)


def test_sparse_events_expand_kpis_for_streamlit():
    definitions = [{"id": "revenue", "name": "Revenue", "description": "Total payments", "sql": "SELECT SUM(payment_value) AS value FROM fact_orders"}]
    insights = [{"id": "i1", "kpi_id": "revenue", "type": "anomaly"}]
    payload = build_lineage_graph(_all_steps(), definitions, insights)
    jsonschema.validate(payload, SCHEMA)
    ids = {node["id"] for node in payload["nodes"]}
    assert {"raw.tables", "clean.products", "dbt.fact_orders", "kpi.revenue", "ins.i1"} <= ids
    assert "kpi.catalog" not in ids
    path = upstream(payload, "revenue")
    assert "parse_dates" not in path["cleaning_rules"]
    assert "translate_category_names" in path["cleaning_rules"]
    assert path["kpi_sql"].startswith("SELECT SUM")
    layers = {node["id"]: node["layer"] for node in payload["nodes"]}
    for edge in payload["edges"]:
        assert edge["from"] in layers and edge["to"] in layers


def test_graph_does_not_write_events(data_root):
    path = _write_events(data_root, "run-1", _all_steps())
    before = path.read_bytes()
    response = graph(_req("graph"))
    assert path.read_bytes() == before
    assert response["status"] == "ok"
    assert response["metrics"]["untracked_steps"] == 0
    assert response["metrics"]["lineage_coverage"] == 1
    assert (data_root / "runs" / "run-1" / "audit" / "lineage_graph.json").is_file()


def test_missing_step_is_untracked(data_root):
    events = [event for event in _all_steps() if event["step"] != "score"]
    _write_events(data_root, "run-1", events)
    response = graph(_req("graph"))
    assert response["status"] == "partial"
    assert "score" in response["warnings"][0]
    comp = completeness(events, {"offline_registry": True})
    assert comp["untracked_transformations"] == ["score"]
    assert comp["coverage"] < 1


def test_raw_tables_are_not_opened(data_root):
    raw = data_root / "runs" / "run-1" / "00_ingest" / "orders.parquet"
    assert find_input({"ingest.orders": "runs/run-1/00_ingest/orders.parquet"}, "orders") is None
    assert not raw.exists()


def test_audit_report_factchecks_and_stays_within_budget(data_root):
    _write_events(data_root, "run-1", _all_steps())
    (data_root / "runs" / "run-1" / "04_kpi").mkdir(parents=True)
    (data_root / "runs" / "run-1" / "05_insights").mkdir(parents=True)
    definitions = [{"id": "revenue", "name": "Revenue", "description": "Total payments received for delivered orders", "sql": "SELECT SUM(payment_value) AS value FROM fact_orders", "unit": "BRL"}]
    insights = [{"id": "i1", "kpi_id": "revenue", "type": "anomaly", "period": "2017-11", "severity": "review", "facts": {"expected": 10, "actual": 12}, "narrative": "should not be copied"}]
    (data_root / "runs" / "run-1" / "04_kpi" / "kpi_definitions.json").write_text(json.dumps(definitions), encoding="utf-8")
    (data_root / "runs" / "run-1" / "05_insights" / "insights.json").write_text(json.dumps(insights), encoding="utf-8")
    response = audit(
        _req(
            "audit",
            inputs={
                "kpi_compute.kpi_definitions": "runs/run-1/04_kpi/kpi_definitions.json",
                "analyse.insights": "runs/run-1/05_insights/insights.json",
            },
        )
    )
    assert response["status"] == "ok"
    assert response["metrics"]["factcheck_first_try_pass"] == 1
    assert response["metrics"]["unsupported_statement_rate"] == 0
    assert len(response["llm_calls"]) <= 8
    report = json.loads((data_root / "runs" / "run-1" / "audit" / "trace_report.json").read_text(encoding="utf-8"))
    markdown = (data_root / "runs" / "run-1" / "audit" / "trace_report.md").read_text(encoding="utf-8")
    assert "Untracked" not in markdown
    assert "should not be copied" not in json.dumps(report["insights"])
    for section in report["sections"]:
        assert fact_check(section["prose"], section["fact_sheet"])
    sheet = next(section["fact_sheet"] for section in report["sections"] if section["id"] == "completeness")
    assert fact_check(completeness_template(sheet), sheet)


def test_prose_fallback_and_second_try(monkeypatch):
    calls = {"n": 0}

    def fake_chat(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return "Revenue grew by 99999."
        return "Still 99999."

    monkeypatch.setattr("app.prose.chat_text", fake_chat)
    sheet = {"total_delta": 12, "period": "2017-11", "kpi_id": "revenue", "definition": {"name": "Revenue", "description": "Total payments"}}
    template = "The logged change is 12."
    assert fact_check(template, sheet)
    result = write_prose(prompt_id="auditor.explain_kpi@v3", fact_sheet=sheet, template=template, lang="en", section="Explain", min_sentences=1, max_sentences=5)
    assert result.source == "template"
    assert result.attempts == 3
    assert result.first_try_pass is False
    assert "99999" not in result.text
    assert fact_check(result.text, sheet)

    calls["n"] = 0

    def recover(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return "Revenue grew by 99999."
        return "The logged change is 12."

    monkeypatch.setattr("app.prose.chat_text", recover)
    recovered = write_prose(prompt_id="auditor.explain_kpi@v3", fact_sheet=sheet, template=template, lang="en", section="Explain", min_sentences=1, max_sentences=5)
    assert recovered.source == "llm"
    assert recovered.attempts == 2
    assert recovered.first_try_pass is False


def test_explain_abstains_when_nothing_is_logged(data_root):
    response = explain(_req("explain", options={"kpi_id": "revenue", "period": "2017-11"}))
    assert response["status"] == "ok"
    assert response["metrics"]["abstained"] is True
    assert response["metrics"]["answer"] == "not enough logged information"
    assert response["llm_calls"] == []


def test_explain_answer_uses_the_matching_driver(data_root, monkeypatch):
    monkeypatch.setattr("app.prose.chat_text", lambda *_args, **_kwargs: "It changed by 99999.")
    monkeypatch.setattr("app.v6.chat_text", lambda *_args, **_kwargs: "It changed by 99999.")
    drivers = [
        {"kpi_id": "revenue", "period": "2017-11", "compare_to": "2017-10", "total_delta": 12, "dimension": "customer_state", "contributions": [{"dimension_value": "SP", "delta": 12}]},
        {"kpi_id": "revenue", "period": "2017-11", "compare_to": "2017-09", "total_delta": 4, "dimension": "customer_state", "contributions": [{"dimension_value": "RJ", "delta": 4}]},
    ]
    folder = data_root / "runs" / "run-1" / "05_insights"
    folder.mkdir(parents=True)
    (folder / "drivers.json").write_text(json.dumps(drivers), encoding="utf-8")
    defs = data_root / "runs" / "run-1" / "04_kpi"
    defs.mkdir(parents=True)
    (defs / "kpi_definitions.json").write_text(
        json.dumps([{"id": "revenue", "name": "Revenue", "description": "Total payments received for delivered orders", "unit": "BRL"}]),
        encoding="utf-8",
    )
    assert select_drivers(drivers, "revenue", "2017-11", "2017-10")["total_delta"] == 12
    response = explain(
        _req(
            "explain",
            options={"kpi_id": "revenue", "period": "2017-11", "compare_to": "2017-10"},
            inputs={
                "analyse.drivers": "runs/run-1/05_insights/drivers.json",
                "kpi_compute.kpi_definitions": "runs/run-1/04_kpi/kpi_definitions.json",
            },
        )
    )
    assert response["metrics"]["abstained"] is False
    assert "99999" not in response["metrics"]["answer"]
    assert "12" in response["metrics"]["answer"]
    assert "SP" in response["metrics"]["answer"]
    assert "RJ" not in response["metrics"]["answer"]
    body = json.loads((data_root / "runs" / "run-1" / "audit" / "explain_answer.json").read_text(encoding="utf-8"))
    assert fact_check(body["answer"], body["fact_sheet"])
    assert body["citations"]
    assert any("delta" in fact_id for row in body["citations"] for fact_id in row["fact_ids"])
    assert response["status"] == "partial"


def _explain_revenue(data_root, drivers: list[dict]):
    folder = data_root / "runs" / "run-1" / "05_insights"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "drivers.json").write_text(json.dumps(drivers), encoding="utf-8")
    defs = data_root / "runs" / "run-1" / "04_kpi"
    defs.mkdir(parents=True, exist_ok=True)
    (defs / "kpi_definitions.json").write_text(
        json.dumps([{"id": "revenue", "name": "Revenue", "description": "Total payments received for delivered orders", "unit": "BRL"}]),
        encoding="utf-8",
    )
    return explain(
        _req(
            "explain",
            options={"kpi_id": "revenue", "period": "2017-11", "compare_to": "2017-10"},
            inputs={
                "analyse.drivers": "runs/run-1/05_insights/drivers.json",
                "kpi_compute.kpi_definitions": "runs/run-1/04_kpi/kpi_definitions.json",
            },
        )
    )


def test_explanation_store_hits_and_changes_key(data_root, monkeypatch):
    monkeypatch.setenv("BIFLOW_PROFILE", "ollama")
    monkeypatch.delenv("EXPLAIN_KPI_VERSION", raising=False)
    monkeypatch.delenv("explain_kpi_version", raising=False)
    monkeypatch.setenv("explain_kpi_version", "v4")
    calls = {"n": 0}

    def fake(*_args, **_kwargs):
        calls["n"] += 1
        return "It changed by 99999."

    monkeypatch.setattr("app.prose.chat_text", fake)
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
    first = _explain_revenue(data_root, drivers)
    assert first["metrics"]["explanation_store"] == "miss"
    assert calls["n"] == 3
    stored_key = first["lineage_events"][0]["params"]["explanation_key"]
    stored_sha = first["lineage_events"][0]["params"]["response_sha256"]
    assert stored_sha == hashlib.sha256(first["metrics"]["answer"].encode()).hexdigest()
    assert (data_root / "auditor" / "explanations" / f"{stored_key}.json").is_file()

    second = _explain_revenue(data_root, drivers)
    assert second["metrics"]["explanation_store"] == "hit"
    assert second["metrics"]["answer"] == first["metrics"]["answer"]
    assert calls["n"] == 3
    assert second["lineage_events"][0]["params"]["explanation_key"] == stored_key
    assert second["lineage_events"][0]["params"]["response_sha256"] == stored_sha

    drivers[0]["total_delta"] = 99
    drivers[0]["contributions"] = [{"dimension_value": "SP", "delta": 99}]
    changed = _explain_revenue(data_root, drivers)
    assert changed["metrics"]["explanation_store"] == "miss"
    assert calls["n"] == 6
    assert changed["lineage_events"][0]["params"]["explanation_key"] != stored_key
    assert changed["metrics"]["answer"] != first["metrics"]["answer"]


def test_explain_requires_kpi_and_period(data_root):
    response = explain(_req("explain", options={"period": "2017-11"}))
    assert response["status"] == "error"
    assert response["error"]["code"] == "BAD_INPUT"


def test_eval_meets_traceability_targets():
    metrics = eval_metrics()
    assert metrics["explain_cases"] == 20
    assert metrics["labelled_claims"] == 60
    assert metrics["lineage_coverage"] == 1
    assert metrics["factcheck_first_try_pass_rate"] >= 0.95
    assert metrics["unsupported_statement_rate"] == 0
    assert metrics["planted_bad_count"] == 15
    assert metrics["bad_prose_set"] == "development"
    assert metrics["bad_prose_detection_rate"] == 1
    assert metrics["number_only_detection_rate"] == 0.2
    assert metrics["valid_prose_count"] == 30
    assert metrics["false_reject_rate"] == 0
    assert metrics["held_out_count"] == 16
    assert metrics["held_out_unsupported"] == 15
    assert metrics["held_out_recall"] == 0.7333
    assert metrics["held_out_recall_before_rules"] == 0.3333
    assert metrics["fresh_held_out_checker_recall"] == 0.0667
    assert metrics["fresh_held_out_judge_recall"] == 1.0
    assert metrics["fresh_held_out_union_recall"] == 1.0
    assert metrics["held_out_false_reject_rate"] == 0
    assert metrics["llm_judge_recall"] == 0.6667
    assert metrics["held_out_union_recall"] == 0.8667
    assert metrics["held_out_union_false_reject_rate"] == 0.0
    assert metrics["judge_false_reject_rate"] == 0.0667
    assert metrics["planted_bad_first_try_pass_rate"] == 0
    assert metrics["faithfulness"] == 1
    assert metrics["driver_recall"] == 1
    assert metrics["readability_mean"] is None
    assert metrics["readability_responses"] == 0
    assert metrics["v4_published_answers"] == 20
    assert metrics["v4_published_faithfulness"] == 0.65


def test_pyvis_accepts_the_payload():
    pytest.importorskip("pyvis")
    from pyvis.network import Network

    payload = build_lineage_graph(_all_steps())
    net = Network(directed=True, notebook=False)
    for node in payload["pyvis"]["nodes"]:
        net.add_node(node["id"], label=node["label"], title=node["title"], level=node["level"])
    for edge in payload["pyvis"]["edges"]:
        net.add_edge(edge["from"], edge["to"], title=edge["title"])
    assert len(net.nodes) == len(payload["nodes"])


def test_fact_sheet_with_nan_does_not_crash_the_checker():
    from app.factcheck import sheet_numbers

    assert sheet_numbers({"p_value": float("nan"), "delta": 12.5, "x": float("inf")}) == {"12.5"}
