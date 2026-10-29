"""Assemble the trace report: structured sections first, then one prose paragraph per section."""

from __future__ import annotations

import time
from typing import Any

from jinja2 import Environment

from .completeness import completeness
from .constants import MAX_LLM_SECTIONS
from .factcheck import continuity_breaks, unsupported_claims
from .factsheet import (
    agent_duration,
    insight_sheet,
    kpi_sheet,
    load_manifest,
    quality_log_count,
    stage_sheet,
)
from .prose import ProseResult, prompt_ref, write_prose
from .templates import completeness_template, insight_template, kpi_template, section_template

_STAGES = (
    ("ingest_quality", "Ingest, validation, and quality score", ("ingest", "validate", "score_before", "score_after")),
    ("profile_clean", "Profiling and cleaning", ("profile", "clean")),
    ("etl", "Warehouse models", ("etl",)),
    ("semantic_kpi", "KPI computation", ("kpi_compute", "kpi_index")),
    ("analyst", "Insights and anomaly checks", ("analyse", "dashboard_config")),
)

_MD = Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True).from_string(
    """# Trace report

Run `{{ run_id }}` for dataset `{{ dataset }}`. Paragraphs were written from a fact sheet. Tables were copied from the logs.

## Completeness

{{ completeness.prose }}

{% if completeness.untracked_transformations %}
Untracked transformations:

{% for step in completeness.untracked_transformations %}
- {{ step }}
{% endfor %}
{% endif %}

## Stages

{% for stage in stages %}
### {{ stage.title }}

{{ stage.prose }}

| Step | Method | Rule | Rows in | Rows out | Rows affected |
|---|---|---|---|---|---|
{% for step in stage.steps %}
| {{ step.step }} | {{ step.method }} | {{ step.rule }} | {{ step.rows_in }} | {{ step.rows_out }} | {{ step.rows_affected }} |
{% endfor %}

{% endfor %}

## KPIs

{{ kpis.prose }}

{% for item in kpis["items"] %}
### {{ item.name }} (`{{ item.kpi_id }}`)

{{ item.description }}

- Unit: {{ item.unit }}
- Source tables: {{ item.sources }}
- Cleaning steps: {{ item.cleaning }}
- Warehouse models: {{ item.models }}
{% if item.sql %}

```sql
{{ item.sql }}
```
{% endif %}

{% endfor %}

## Insights

{{ insights.prose }}

{% for item in insights["items"] %}
### {{ item.id }}

- KPI: {{ item.kpi_id }}
- Type: {{ item.type }}
- Period: {{ item.period }}
- Severity: {{ item.severity }}
- Facts: {{ item.facts }}

{% endfor %}

## Row continuity

{% if continuity %}
{% for item in continuity %}
- `{{ item.from_step }}` wrote {{ item.rows_out }} rows of `{{ item.dataset }}` and `{{ item.to_step }}` read {{ item.rows_in }}.
{% endfor %}
{% else %}
Consecutive steps that share a dataset have matching row counts.
{% endif %}

## Fact-check

Sections checked: {{ factcheck.sections }}. First-try pass rate: {{ factcheck.first_try_pass_rate }}. Unsupported-statement rate after fallback: {{ factcheck.unsupported_statement_rate }}.
"""
)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "/").replace("`", "'").replace("\n", " ")


def _group(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("agent") == "auditor":
            continue
        agent = str(event.get("agent") or "unknown")
        grouped.setdefault(agent, []).append(event)
    return grouped


def _job(section_id: str, title: str, fact_sheet: dict[str, Any], template: str, kind: str) -> dict[str, Any]:
    return {"id": section_id, "title": title, "fact_sheet": fact_sheet, "template": template, "kind": kind}


def build_trace(
    *,
    run_id: str,
    dataset: str,
    lang: str,
    events: list[dict[str, Any]],
    graph: dict[str, Any],
    definitions: list[dict[str, Any]],
    insights: list[dict[str, Any]],
    inputs: dict[str, str],
    options: dict[str, Any],
    deadline: float | None = None,
) -> tuple[dict[str, Any], str, list[str]]:
    manifest = load_manifest(run_id)
    grouped = _group(events)
    known = {agent for agent, _title, _stages in _STAGES}
    jobs: list[dict[str, Any]] = []
    stage_views: list[dict[str, Any]] = []

    for agent, title, stage_names in _STAGES:
        agent_events = grouped.get(agent) or []
        if not agent_events:
            continue
        sheet = stage_sheet(title, agent, agent_events, agent_duration(manifest, list(stage_names)))
        if agent == "profile_clean":
            fixes = quality_log_count(inputs)
            if fixes is not None:
                sheet["fix_count"] = fixes
        jobs.append(_job(agent, title, sheet, section_template(sheet, lang), "stage"))
        stage_views.append({"agent": agent, "title": title, "steps": sheet["steps"]})

    others = []
    for agent, agent_events in grouped.items():
        if agent in known:
            continue
        title = agent.replace("_", " ")
        sheet = stage_sheet(title, agent, agent_events, None)
        job = _job(agent, title, sheet, section_template(sheet, lang), "stage")
        others.append(job)
        stage_views.append({"agent": agent, "title": title, "steps": sheet["steps"]})

    kpi_view = {"prose": "", "prose_source": "skipped", "items": []}
    if definitions:
        sheet = kpi_sheet(definitions, graph)
        jobs.append(_job("kpis", "KPI definitions", sheet, kpi_template(sheet, lang), "kpis"))
        kpi_view = {"items": sheet["kpis"]}

    insight_view = {"prose": "", "prose_source": "skipped", "items": []}
    if insights:
        sheet = insight_sheet(insights)
        jobs.append(_job("insights", "Insights", sheet, insight_template(sheet, lang), "insights"))
        insight_view = {"items": sheet["insights"]}

    comp = completeness(events, options)
    comp_sheet = {
        "registered_count": comp["registered_count"],
        "observed_count": comp["observed_count"],
        "untracked_count": comp["untracked_count"],
        "coverage_pct": comp["coverage_pct"],
        "untracked_transformations": comp["untracked_transformations"],
        "registered_steps": comp["registered_steps"],
    }
    jobs.append(_job("completeness", "Completeness", comp_sheet, completeness_template(comp_sheet, lang), "completeness"))
    jobs.extend(others)

    warnings: list[str] = []
    if len(jobs) > MAX_LLM_SECTIONS:
        skipped = ", ".join(job["title"] for job in jobs[MAX_LLM_SECTIONS:])
        warnings.append(f"LLM budget of {MAX_LLM_SECTIONS} section calls reached; template text used for {skipped}")

    results: dict[str, ProseResult] = {}
    for index, job in enumerate(jobs):
        if index >= MAX_LLM_SECTIONS or (deadline is not None and time.monotonic() > deadline):
            text = job["template"]
            results[job["id"]] = ProseResult(
                text, "template", 0, None, "template text used without a model call", unsupported_claims(text, job["fact_sheet"])
            )
            continue
        results[job["id"]] = write_prose(
            prompt_id=prompt_ref("section_prose", options),
            fact_sheet=job["fact_sheet"],
            template=job["template"],
            lang=lang,
            section=job["title"],
            deadline=deadline,
            judge=bool(options.get("llm_judge")),
        )

    for job in jobs:
        result = results[job["id"]]
        if result.warning and result.warning != "template text used without a model call":
            warnings.append(f"{job['title']}: {result.warning}")

    tried = [result for result in results.values() if result.first_try_pass is not None]
    first_rate = 1.0 if not tried else round(sum(1 for result in tried if result.first_try_pass) / len(tried), 4)
    published = list(results.values())
    bad = 0
    for job in jobs:
        result = results[job["id"]]
        if unsupported_claims(result.text, job["fact_sheet"]):
            bad += 1
    unsupported = 0.0 if not published else round(bad / len(published), 4)
    breaks = continuity_breaks(events)
    for item in breaks:
        warnings.append(
            f"row continuity break: {item['from_step']} wrote {item['rows_out']} rows "
            f"and {item['to_step']} read {item['rows_in']}"
        )
    if comp["untracked_transformations"]:
        warnings.append("untracked transformations: " + ", ".join(comp["untracked_transformations"]))

    def _attach(view: dict[str, Any], section_id: str) -> None:
        result = results.get(section_id)
        if result is None:
            return
        view["prose"] = result.text
        view["prose_source"] = result.source

    for view in stage_views:
        _attach(view, view["agent"])
        result = results[view["agent"]]
        view["fact_sheet"] = next(job["fact_sheet"] for job in jobs if job["id"] == view["agent"])
        view["steps"] = [
            {
                "step": _cell(step.get("step")),
                "method": _cell(step.get("method")),
                "rule": _cell(step.get("rule")),
                "rows_in": _cell(step.get("rows_in")),
                "rows_out": _cell(step.get("rows_out")),
                "rows_affected": _cell(step.get("rows_affected")),
            }
            for step in view["steps"]
        ]
        view["prose"] = result.text
        view["prose_source"] = result.source

    if definitions:
        _attach(kpi_view, "kpis")
        kpi_view["fact_sheet"] = next(job["fact_sheet"] for job in jobs if job["id"] == "kpis")
        kpi_view["items"] = [
            {
                "kpi_id": item.get("kpi_id"),
                "name": _cell(item.get("name")),
                "description": _cell(item.get("description")),
                "unit": _cell(item.get("unit")),
                "sources": _cell(", ".join(item.get("source_tables") or []) or "none logged"),
                "cleaning": _cell(", ".join(item.get("cleaning_steps") or []) or "none logged"),
                "models": _cell(", ".join(item.get("dbt_models") or []) or "none logged"),
                "sql": str(item.get("sql") or "").replace("```", "'''"),
            }
            for item in kpi_view["items"]
        ]
    if insights:
        _attach(insight_view, "insights")
        insight_view["fact_sheet"] = next(job["fact_sheet"] for job in jobs if job["id"] == "insights")
        insight_view["items"] = [
            {
                "id": _cell(item.get("id")),
                "kpi_id": _cell(item.get("kpi_id")),
                "type": _cell(item.get("type")),
                "period": _cell(item.get("period")),
                "severity": _cell(item.get("severity")),
                "facts": _cell(item.get("facts")),
            }
            for item in insight_view["items"]
        ]

    comp_result = results["completeness"]
    comp_out = dict(comp)
    comp_out["prose"] = comp_result.text
    comp_out["prose_source"] = comp_result.source
    comp_out["fact_sheet"] = comp_sheet

    factcheck = {
        "sections": len(jobs),
        "first_try_passes": sum(1 for result in tried if result.first_try_pass),
        "first_try_pass_rate": first_rate,
        "unsupported_statement_rate": unsupported,
        "fallbacks": sum(1 for result in results.values() if result.source == "template"),
    }
    report = {
        "run_id": run_id,
        "dataset": dataset,
        "stages": stage_views,
        "kpis": kpi_view,
        "insights": insight_view,
        "completeness": comp_out,
        "continuity": breaks,
        "factcheck": factcheck,
        "sections": [
            {
                "id": job["id"],
                "title": job["title"],
                "prose": results[job["id"]].text,
                "prose_source": results[job["id"]].source,
                "fact_sheet": job["fact_sheet"],
            }
            for job in jobs
        ],
    }
    markdown = _MD.render(
        run_id=run_id,
        dataset=dataset,
        stages=stage_views,
        kpis=kpi_view if definitions else {"prose": "No KPI definitions were logged.", "items": []},
        insights=insight_view if insights else {"prose": "No insights were logged.", "items": []},
        completeness=comp_out,
        continuity=breaks,
        factcheck=factcheck,
    )
    if not definitions:
        kpi_view["prose"] = "No KPI definitions were logged."
    if not insights:
        insight_view["prose"] = "No insights were logged."
    return report, markdown, warnings
