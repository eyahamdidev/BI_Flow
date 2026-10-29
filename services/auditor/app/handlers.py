"""Auditor handlers (BO2): lineage graph, trace report, and Explain this KPI."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from biflow_contracts import RunRequest
from biflow_contracts.biflow_llm import drain_calls, resolve_models

from .citations import enrich_citations
from .completeness import completeness
from .constants import ABSTAIN, AUDIT_TIMEOUT_S, EXPLAIN_TIMEOUT_S
from .explain_store import explanation_key, load_explanation, response_sha256, save_explanation
from .factcheck import cite_sentences, missing_numbers, unsupported_claims
from .factsheet import (
    explain_fact_sheet,
    load_definitions,
    load_drivers,
    load_graph,
    load_insights,
    sheet_is_empty,
)
from .graph_builder import build_lineage_graph, upstream
from .io_utils import artifact, events_path, load_events, run_dir, write_json, write_text
from .prose import explain_kpi_default, prompt_ref, write_prose
from .report import build_trace
from .templates import explain_template


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _lineage(req: RunRequest, step: str, outputs: list[dict[str, Any]], method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "run_id": req.run_id,
        "ts": _now(),
        "agent": "auditor",
        "step": step,
        "inputs": [{"name": key, "path": value} for key, value in req.inputs.items()],
        "outputs": [{"name": item["name"], "path": item["path"]} for item in outputs],
        "rule": None,
        "rows_affected": None,
        "method": method,
        "params": params,
        "llm": None,
    }


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "outputs": [],
        "metrics": {},
        "warnings": [],
        "lineage_events": [],
        "llm_calls": drain_calls(),
        "error": {"code": code, "message": message},
    }


def graph(req: RunRequest) -> dict[str, Any]:
    drain_calls()
    events, warnings = load_events(events_path(req.run_id, req.inputs, req.options))
    definitions = load_definitions(req.inputs)
    insights = load_insights(req.inputs)
    payload = build_lineage_graph(events, definitions, insights)
    comp = completeness(events, req.options)
    if comp["untracked_transformations"]:
        warnings.append("untracked transformations: " + ", ".join(comp["untracked_transformations"]))
    out = run_dir(req.run_id) / "audit" / "lineage_graph.json"
    write_json(out, payload)
    outputs = [artifact("lineage_graph", "json", out, "Lineage graph")]
    return {
        "status": "partial" if warnings else "ok",
        "outputs": outputs,
        "metrics": {
            "nodes": len(payload["nodes"]),
            "edges": len(payload["edges"]),
            "untracked_steps": comp["untracked_count"],
            "lineage_coverage": comp["coverage"],
        },
        "warnings": warnings,
        "lineage_events": [_lineage(req, "build_lineage_graph", outputs, "deterministic", {"nodes": len(payload["nodes"])})],
        "llm_calls": drain_calls(),
    }


def _audit(req: RunRequest) -> dict[str, Any]:
    drain_calls()
    deadline = time.monotonic() + AUDIT_TIMEOUT_S
    events, warnings = load_events(events_path(req.run_id, req.inputs, req.options))
    definitions = load_definitions(req.inputs)
    insights = load_insights(req.inputs)
    graph_payload = load_graph(req.inputs)
    if not graph_payload.get("nodes"):
        graph_payload = build_lineage_graph(events, definitions, insights)
    report, markdown, report_warnings = build_trace(
        run_id=req.run_id,
        dataset=req.dataset,
        lang=req.lang,
        events=events,
        graph=graph_payload,
        definitions=definitions,
        insights=insights,
        inputs=req.inputs,
        options=req.options,
        deadline=deadline,
    )
    warnings.extend(report_warnings)
    folder = run_dir(req.run_id) / "audit"
    json_path = folder / "trace_report.json"
    md_path = folder / "trace_report.md"
    write_json(json_path, report)
    write_text(md_path, markdown if markdown.endswith("\n") else markdown + "\n")
    outputs = [
        artifact("trace_report_md", "md", md_path, "Trace report"),
        artifact("trace_report_json", "json", json_path, "Trace report"),
    ]
    factcheck = report["factcheck"]
    used_model = any(section["prose_source"] == "llm" for section in report["sections"])
    return {
        "status": "partial" if warnings else "ok",
        "outputs": outputs,
        "metrics": {
            "sections": factcheck["sections"],
            "factcheck_first_try_pass": factcheck["first_try_pass_rate"],
            "unsupported_statement_rate": factcheck["unsupported_statement_rate"],
            "lineage_coverage": report["completeness"]["coverage"],
            "untracked_steps": report["completeness"]["untracked_count"],
        },
        "warnings": warnings,
        "lineage_events": [
            _lineage(req, "write_trace_report", outputs, "llm_assisted" if used_model else "deterministic", {"sections": factcheck["sections"]})
        ],
        "llm_calls": drain_calls(),
    }


def _explain(req: RunRequest) -> dict[str, Any]:
    drain_calls()
    kpi_id = req.options.get("kpi_id")
    period = req.options.get("period")
    if not kpi_id or period in (None, ""):
        return _error("BAD_INPUT", "options.kpi_id and options.period are required")
    compare_to = req.options.get("compare_to") or None
    definitions = load_definitions(req.inputs)
    insights = load_insights(req.inputs)
    drivers = load_drivers(req.inputs)
    graph_payload = load_graph(req.inputs)
    sheet = explain_fact_sheet(
        kpi_id=str(kpi_id),
        period=str(period),
        compare_to=str(compare_to) if compare_to else None,
        definitions=definitions,
        graph=graph_payload,
        drivers_doc=drivers,
        insights=insights,
    )
    path = upstream(graph_payload, str(kpi_id)) if graph_payload.get("nodes") else {"kpi_id": str(kpi_id), "found": False}
    warnings: list[str] = []
    citations: list[dict[str, Any]] = []
    prompt_id = prompt_ref("explain_kpi", req.options, default=explain_kpi_default())
    model_name = resolve_models().get("llm_main") or ""
    store_key = explanation_key(
        str(kpi_id),
        str(period),
        str(compare_to) if compare_to else None,
        sheet,
        prompt_id,
        model_name,
        req.lang,
    )
    stored = None if sheet_is_empty(sheet) else load_explanation(store_key)
    if sheet_is_empty(sheet):
        answer = ABSTAIN
        source = "abstain"
        attempts = 0
        issues: list[str] = []
        numbers: list[str] = []
        status = "ok"
        store_state = "abstain"
    elif stored:
        answer = stored["text"]
        source = str(stored.get("prose_source") or "store")
        attempts = int(stored.get("attempts") or 0)
        issues = unsupported_claims(answer, sheet)
        numbers = missing_numbers(answer, sheet)
        citations = list(stored.get("citations") or [])
        citation_method = str(stored.get("citation_method") or "inferred_overlap")
        if stored.get("warning"):
            warnings.append(str(stored["warning"]))
        status = "partial" if warnings or issues else "ok"
        store_state = "hit"
    else:
        result = write_prose(
            prompt_id=prompt_id,
            fact_sheet=sheet,
            template=explain_template(sheet, req.lang),
            lang=req.lang,
            section=f"Explain {kpi_id} for {period}",
            min_sentences=3,
            max_sentences=5,
            deadline=time.monotonic() + EXPLAIN_TIMEOUT_S,
            judge=bool(req.options.get("llm_judge")),
        )
        answer = result.text
        source = result.source
        attempts = result.attempts
        issues = unsupported_claims(answer, sheet)
        numbers = missing_numbers(answer, sheet)
        if result.citation_method == "declared_field_id":
            citations = result.citations or []
            citation_method = "declared_field_id"
        else:
            citations = cite_sentences(answer, sheet)
            citation_method = "inferred_overlap"
        if result.warning:
            warnings.append(result.warning)
        status = "partial" if warnings or issues else "ok"
        store_state = "miss"
        save_explanation(
            {
                "key": store_key,
                "response_sha256": response_sha256(answer),
                "text": answer,
                "prose_source": source,
                "attempts": attempts,
                "warning": result.warning,
                "citations": citations,
                "citation_method": citation_method,
                "prompt_version": prompt_id,
                "model": model_name,
            }
        )
    text_sha = response_sha256(answer)
    if not sheet_is_empty(sheet):
        logged_events, _event_notes = load_events(events_path(req.run_id, req.inputs, req.options))
        citations = enrich_citations(citations, sheet, logged_events, req.lang)
    body = {
        "kpi_id": str(kpi_id),
        "period": str(period),
        "compare_to": compare_to,
        "abstained": answer == ABSTAIN,
        "answer": answer,
        "prose_source": source,
        "fact_sheet": {} if answer == ABSTAIN else sheet,
        "upstream": path,
        "citations": citations,
        "citation_method": citation_method if not sheet_is_empty(sheet) else "inferred_overlap",
        "factcheck": {"passed": not issues, "attempts": attempts, "missing_numbers": numbers, "issues": issues},
        "explanation_key": store_key,
        "response_sha256": text_sha,
        "explanation_store": store_state,
    }
    out = run_dir(req.run_id) / "audit" / "explain_answer.json"
    write_json(out, body)
    outputs = [artifact("explain_answer", "json", out, "Explain this KPI")]
    method = "llm_assisted" if source == "llm" else "deterministic"
    return {
        "status": status,
        "outputs": outputs,
        "metrics": {
            "answer": answer,
            "abstained": body["abstained"],
            "prose_source": source,
            "factcheck_attempts": attempts,
            "explanation_store": store_state,
            "response_sha256": text_sha,
            "citations": citations,
        },
        "warnings": warnings,
        "lineage_events": [
            _lineage(
                req,
                "explain_kpi",
                outputs,
                method,
                {"kpi_id": str(kpi_id), "period": str(period), "explanation_key": store_key, "response_sha256": text_sha},
            )
        ],
        "llm_calls": drain_calls(),
    }


# Hard LLM budgets (enforced inside the LLM helper, per call): the prose deadlines above are checked between calls, so a
# slow provider could still keep one call running past the gateway's budget. Templates take over when time is up.
def audit(req: RunRequest) -> dict[str, Any]:
    from biflow_contracts.biflow_llm import llm_deadline

    with llm_deadline(AUDIT_TIMEOUT_S):
        return _audit(req)


def explain(req: RunRequest) -> dict[str, Any]:
    from biflow_contracts.biflow_llm import llm_deadline

    with llm_deadline(EXPLAIN_TIMEOUT_S):
        return _explain(req)
