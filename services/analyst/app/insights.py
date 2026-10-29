"""Analyst stage (mode `analyse`): KPI table -> insights.json + drivers.json (BO6).

Code finds everything (trends, anomalies, drivers, rule-matched recommendations) and writes a template narrative.
The LLM only REWRITES narratives for the most important insights, using the insight's facts; a code fact-check rejects
any number not in the facts (then the template stays). Recommendations come only from the rule table.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from . import analysis as A

NUM = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")
MAX_LLM_NARRATIVES = 10
SEV_RANK = {"high": 0, "review": 1, "info": 2}


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "configs" / "datasets").is_dir():
            return p
    return Path.cwd().resolve()


def find_input(inputs: dict[str, str], name: str) -> Path | None:
    for key, rel in inputs.items():
        if key.split(".")[-1] == name:
            return data_dir() / rel
    return None


def _event(run_id: str, step: str, **kw: Any) -> dict[str, Any]:
    return {"event_id": str(uuid.uuid4()), "run_id": run_id, "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "agent": "analyst", "step": step, "method": "deterministic", **kw}


# ---------------------------------------------------------------- formatting + templates
def fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "n/a"
    if unit == "ratio":
        return f"{100 * v:.1f}%"
    if unit == "BRL":
        return f"R$ {v:,.2f}"
    return f"{v:,.2f}"


def template(ins: dict[str, Any], d: dict[str, Any]) -> str:
    f, unit, name = ins["facts"], d.get("unit", ""), d.get("name", ins["kpi_id"])
    if ins["type"] == "trend":
        return (f"{name} has been trending {f['direction']} over the last {f['months']} complete months "
                f"({fmt(f['first_value'], unit)} in {f['window_start']} to {fmt(f['last_value'], unit)} in {f['window_end']}).")
    if ins["type"] == "anomaly":
        return (f"{name} in {ins['period']} was unusually {f['direction']}: {fmt(f['actual'], unit)} against about "
                f"{fmt(f['expected'], unit)} expected from the trend.")
    if ins["type"] == "driver":
        tops = ", ".join(f"{c['dimension_value']} ({'+' if c['delta'] >= 0 else ''}{fmt(c['delta'], unit)})" for c in f["top_drivers"])
        return (f"{name} changed by {'+' if f['total_delta'] >= 0 else ''}{fmt(f['total_delta'], unit)} from {f['compare_to']} "
                f"to {ins['period']}; by {f['dimension']}, the largest contributions were {tops}.")
    return f["action"]


# ---------------------------------------------------------------- fact-checked LLM rewrite
def _allowed_numbers(facts: Any, unit: str) -> set[float]:
    out: set[float] = set()

    def add(x: float) -> None:
        for v in (x, abs(x)) + ((100 * x, 100 * abs(x)) if unit == "ratio" or abs(x) <= 1 else ()):
            for nd in (0, 1, 2, 3, 4):
                out.add(round(v, nd))

    def walk(o: Any) -> None:
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            add(float(o))
        elif isinstance(o, str):
            for n in NUM.findall(o):
                add(float(n.replace(",", "")))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(facts)
    return out


def unsupported(text: str, facts: Any, unit: str) -> list[str]:
    allowed = _allowed_numbers(facts, unit)
    bad = []
    for n in NUM.findall(text):
        v = float(n.replace(",", ""))
        if not any(abs(v - a) <= 0.005 * max(1.0, abs(a)) for a in allowed):
            bad.append(n)
    return bad


def rewrite(ins: dict[str, Any], d: dict[str, Any]) -> tuple[str, str]:
    """(narrative, source) with source = llm | template."""
    from biflow_contracts.biflow_llm import LLMUnavailable, chat_text

    p = yaml.safe_load((repo_root() / "prompts" / "analyst" / "narrative" / "v1.yaml").read_text(encoding="utf-8"))
    facts = {"kpi": d.get("name"), "unit": d.get("unit"), "direction_good": d.get("direction"), "type": ins["type"],
             "period": ins.get("period"), **ins["facts"]}
    system = p["text"].format(facts=json.dumps(facts, default=str))
    user = f"Draft to improve (same facts): {ins['narrative']}"
    for _ in range(2):
        try:
            text = chat_text(f"analyst.narrative@v{p['version']}", system=system, user=user, role=p["model_role"], temperature=0.3).strip()
        except LLMUnavailable:
            return ins["narrative"], "template"
        bad = unsupported(text, facts, d.get("unit", ""))
        if not bad and text:
            return text, "llm"
        user = f"Your answer used numbers that are not in the facts: {bad}. Rewrite using only numbers from the facts."
    return ins["narrative"], "template"


# ---------------------------------------------------------------- the stage
def _rules(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    ref = cfg.get("recommendations_file")
    if not ref:
        return []
    p = repo_root() / ref
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or []) if p.exists() else []


def analyse(req: Any) -> dict[str, Any]:
    t0 = time.perf_counter()
    vp, dp = find_input(req.inputs, "kpi_values"), find_input(req.inputs, "kpi_definitions")
    if not vp or not vp.exists() or not dp or not dp.exists():
        return {"status": "error", "error": {"code": "BAD_INPUT", "message": "missing inputs kpi_values / kpi_definitions"}}
    cfg_path = repo_root() / (req.config_ref or f"configs/datasets/{req.dataset}.yaml")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    values = pd.read_parquet(vp)
    defs = {d["id"]: d for d in json.loads(dp.read_text(encoding="utf-8"))}
    out_dir = data_dir() / "runs" / req.run_id / "05_insights"
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = f"runs/{req.run_id}/05_insights"

    insights: list[dict[str, Any]] = []
    drivers: list[dict[str, Any]] = []
    series: dict[str, pd.Series] = {}
    trends: dict[str, dict[str, Any]] = {}
    incomplete: dict[str, list[str]] = {}
    counts = {"trend": 0, "anomaly": 0, "driver": 0, "recommendation": 0}

    def add(kid: str, typ: str, period: str | None, severity: str, facts: dict[str, Any], rule_id: str | None, source: str) -> dict:
        ins = {"id": f"{typ}-{kid}-{period or 'all'}-{len(insights)}", "kpi_id": kid, "type": typ, "period": period,
               "severity": severity, "facts": facts, "narrative": "", "rule_id": rule_id, "source": source}
        ins["narrative"] = template(ins, defs[kid])
        insights.append(ins)
        counts[typ] += 1
        return ins

    for kid, d in defs.items():
        kv = values[values.kpi_id == kid]
        total = kv[kv.dimension == "total"]
        good = A.complete_periods(total)
        incomplete[kid] = sorted(set(total.period) - set(good))
        s = total.set_index("period")["value"].reindex(good)
        series[kid] = s
        bad_dir = "down" if d.get("direction") == "higher_is_better" else ("up" if d.get("direction") == "lower_is_better" else None)

        tr = A.trend(s)
        if tr:
            trends[kid] = tr
            if tr["direction"] != "flat":
                add(kid, "trend", tr["window_end"], "review" if tr["direction"] == bad_dir else "info", tr, None, "model")
        for an in A.anomalies(s):
            add(kid, "anomaly", an["period"], an["severity"], an, None, "model")

        # drivers: every consecutive pair of complete months, every declared dimension (most telling first)
        for prev, cur in zip(good, good[1:], strict=False):
            tt, tp = float(s[cur]), float(s[prev])
            decs = []
            for dim in d.get("dimensions") or []:
                cut = kv[(kv.dimension == dim) & kv.period.isin([prev, cur])]
                if cut.empty:
                    continue
                dec = A.decompose(cut, cur, prev, d.get("aggregation") == "additive", tt, tp)
                dec.update(kpi_id=kid, dimension=dim, aggregation=d.get("aggregation"))
                dec["contributions"] = dec["contributions"][:12]  # top 12 by |delta|; the tail stays in the file below
                decs.append(dec)
            decs.sort(key=lambda x: -A.concentration(x))
            drivers.extend(decs)
            if cur == good[-1] and decs and abs(decs[0]["total_delta"]) > 0:
                best = decs[0]
                tops = [c for c in best["contributions"] if c["dimension_value"] != "(unexplained)"][:3]
                add(kid, "driver", cur, "info", {"dimension": best["dimension"], "compare_to": prev, "total_delta": best["total_delta"],
                                                 "value_t": best["value_t"], "value_prev": best["value_prev"],
                                                 "top_drivers": [{"dimension_value": c["dimension_value"], "delta": c["delta"]} for c in tops]},
                    None, "rule")

    # recommendations: rule table only (the LLM cannot add actions)
    for rule in _rules(cfg):
        w = rule.get("when", {})
        kid = w.get("kpi")
        if kid not in defs:
            continue
        ok, facts = True, {"kpi_id": kid}
        if "trend" in w:
            ok &= trends.get(kid, {}).get("direction") == w["trend"]
            facts["trend"] = trends.get(kid, {}).get("direction")
        if "anomaly" in w:
            hits = [i for i in insights if i["kpi_id"] == kid and i["type"] == "anomaly" and i["facts"]["direction"] == w["anomaly"]]
            ok &= bool(hits)
            facts["period"] = hits[-1]["period"] if hits else None
        if "correlated_with" in w and ok:
            r = A.correlation(series.get(kid, pd.Series(dtype=float)), series.get(w["correlated_with"], pd.Series(dtype=float)))
            ok &= r is not None and abs(r) >= 0.5
            facts["correlation"] = r
        latest = [x for x in drivers if x["kpi_id"] == kid and series[kid].size and x["period"] == series[kid].index[-1]]
        if "top_driver_dimension" in w and ok:
            pick = next((x for x in latest if x["dimension"] == w["top_driver_dimension"]), None)
            ok &= pick is not None
            if pick:
                latest = [pick]
        if not ok:
            continue
        tops = [c["dimension_value"] for c in (latest[0]["contributions"] if latest else []) if c["dimension_value"] != "(unexplained)"][:3]
        facts.update(top_drivers=tops, rule=w)
        action = rule["action"].format(top_drivers=", ".join(tops) or "the main segments", period=facts.get("period") or "the latest month")
        facts["action"] = action
        add(kid, "recommendation", facts.get("period") or (series[kid].index[-1] if series[kid].size else None), "high", facts, rule["id"], "rule")

    # LLM rewrite of the most important narratives (fact-checked), never of the facts. Bounded by a time budget:
    # rewrites run 4 at a time; whatever is not back within LLM_BUDGET_S keeps its (always correct) template.
    from concurrent.futures import ThreadPoolExecutor, wait

    from biflow_contracts.biflow_llm import drain_calls

    llm_on = os.getenv("BIFLOW_ANALYST_LLM", "1") != "0"
    budget = float(os.getenv("LLM_BUDGET_S", "45"))
    narr = {"llm": 0, "template": 0}
    calls: list[Any] = []
    ranked = sorted(insights, key=lambda i: (SEV_RANK[i["severity"]], i["type"] != "recommendation"))
    chosen = ranked[:MAX_LLM_NARRATIVES] if llm_on else []

    def job(ins: dict[str, Any]) -> tuple[str, str, list[Any]]:
        text, src = rewrite(ins, defs[ins["kpi_id"]])
        return text, src, drain_calls()  # the call log is per thread: hand it back to the main thread

    pool = ThreadPoolExecutor(max_workers=4)
    futures = {pool.submit(job, ins): ins for ins in chosen}
    done, _ = wait(futures, timeout=budget)
    pool.shutdown(wait=False, cancel_futures=True)
    for fut, ins in futures.items():
        if fut in done and fut.exception() is None:
            text, src, c = fut.result()
            ins["narrative"] = text
            calls.extend(c)
        else:
            src = "template"
        ins["facts"]["narrative_source"] = src
    for ins in insights:
        src = ins["facts"].setdefault("narrative_source", "template")
        narr[src] += 1

    (out_dir / "insights.json").write_text(json.dumps(insights, indent=2, default=str), encoding="utf-8")
    (out_dir / "drivers.json").write_text(json.dumps({"drivers": drivers, "incomplete_periods": incomplete}, indent=2, default=str), encoding="utf-8")
    ev = [
        _event(req.run_id, "detect_trends", rule=f"linregress over last {A.TREND_WINDOW} complete months, p<{A.P_SIGNIFICANT}",
               rows_affected=counts["trend"], method="ml"),
        _event(req.run_id, "detect_anomalies", rule=f"robust z (median/MAD) on detrended series, |z|>={A.Z_REVIEW}",
               rows_affected=counts["anomaly"], method="ml"),
        _event(req.run_id, "decompose_drivers", rule="delta split by dimension (additive / mix+rate), sums to total delta",
               rows_affected=len(drivers)),
        _event(req.run_id, "match_recommendations", rule=f"rule table {cfg.get('recommendations_file')}", rows_affected=counts["recommendation"]),
        _event(req.run_id, "write_narratives", rule="template; LLM rewrite of top insights with numeric fact-check",
               rows_affected=narr["llm"], method="llm_assisted" if narr["llm"] else "deterministic"),
    ]
    return {
        "status": "ok",
        "outputs": [{"name": "insights", "kind": "json", "path": f"{rel}/insights.json", "rows": len(insights)},
                    {"name": "drivers", "kind": "json", "path": f"{rel}/drivers.json", "rows": len(drivers)}],
        "metrics": {"insights": len(insights), "trends": counts["trend"], "anomalies": counts["anomaly"],
                    "drivers": counts["driver"], "recommendations": counts["recommendation"], "driver_rows": len(drivers),
                    "narratives_llm": narr["llm"], "narratives_template": narr["template"],
                    "seconds": round(time.perf_counter() - t0, 2)},
        "llm_calls": calls,
        "lineage_events": ev,
    }
