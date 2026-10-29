"""BO1 benchmark harness: is time-to-insight measurably reduced, and is the LLM off the critical path for numbers?

    python -m app.cli bench --dataset olist_sample --runs 5

What it measures (spec BO1 "Experiments" + "Metrics"):
  1. N full runs           -> end-to-end and per-stage time, p50 / p95
  2. cold vs cached LLM    -> run 1 starts with an empty LLM cache, runs 2..N reuse it
  3. LLM share of time     -> milliseconds spent waiting for the LLM per stage (from llm_calls)
  4. reproducibility       -> ETL mart fingerprints must be identical in every run (numbers never depend on the LLM)
  5. --resume vs full      -> re-run the last run from `resume_from` and compare with a full run
  6. manual baseline       -> docs/manual_baseline.yaml (measured by a person) -> manual / automated ratio

Writes data/bench/<timestamp>/report.json and report.md (the table for the report).
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import runner


def _pct(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (honest for small N: with 5 runs, p95 is the slowest run)."""
    if not values:
        return None
    v = sorted(values)
    return round(v[max(0, math.ceil(q * len(v)) - 1)], 2)


def _llm_ms(m: dict[str, Any]) -> dict[str, float]:
    """Seconds spent in real (non-cached) LLM calls, per stage, incl. the gateway summary."""
    out: dict[str, float] = {}
    for name, st in m["stages"].items():
        ms = sum((c.get("ms") or 0) for c in st.get("llm_calls", []) if not c.get("cache_hit"))
        if ms:
            out[name] = round(ms / 1000, 2)
    ms = sum((c.get("ms") or 0) for c in (m.get("summary") or {}).get("llm_calls", []) if not c.get("cache_hit"))
    if ms:
        out["summarize"] = round(ms / 1000, 2)
    return out


def _calls(m: dict[str, Any]) -> tuple[int, int]:
    calls = [c for st in m["stages"].values() for c in st.get("llm_calls", [])] + (m.get("summary") or {}).get("llm_calls", [])
    return len(calls), sum(1 for c in calls if c.get("cache_hit"))


def _baseline() -> dict[str, Any] | None:
    f = runner.repo_root() / "docs" / "manual_baseline.yaml"
    if not f.exists():
        return None
    b = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    steps = b.get("steps") or {}
    if any(v is None for v in steps.values()) or not steps:
        return {"measured": False, "by": b.get("measured_by")}
    return {"measured": True, "by": b.get("measured_by"), "minutes_total": round(sum(steps.values()), 1), "steps": steps}


def bench(dataset: str, runs: int = 5, cold_first: bool = True, resume_from: str = "etl") -> dict[str, Any]:
    out_dir = runner.data_dir() / "bench" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(__import__("os").getenv("BIFLOW_CACHE", ".cache/llm.sqlite"))
    if cold_first and cache.exists():
        cache.unlink()  # run 1 = cold: every LLM call really goes to the provider

    manifests, walls = [], []
    for i in range(runs):
        t0 = time.perf_counter()
        m = runner.run_pipeline(dataset)
        walls.append(round(time.perf_counter() - t0, 2))
        manifests.append(m)
        print(f"  run {i + 1}/{runs}: {m['run_id']} {m['status']} {walls[-1]} s", flush=True)

    # --resume experiment on the last run: redo `resume_from` and everything after it
    last = manifests[-1]
    t0 = time.perf_counter()
    resumed = runner.run_pipeline(dataset, run_id=last["run_id"], resume=True, rerun_from=resume_from)
    resume_wall = round(time.perf_counter() - t0, 2)

    stages = list(manifests[0]["stages"])
    per_stage = {}
    for s in stages:
        secs = [m["stages"][s].get("seconds") for m in manifests if m["stages"][s].get("seconds") is not None]
        per_stage[s] = {"p50": _pct(secs, 0.5), "p95": _pct(secs, 0.95),
                        "source": "mock" if manifests[0]["stages"][s].get("mock") else "real"}
    fps = [((m["stages"].get("etl") or {}).get("metrics") or {}).get("fingerprints") for m in manifests]
    llm = [_llm_ms(m) for m in manifests]
    calls = [_calls(m) for m in manifests]
    base = _baseline()
    p50_wall = _pct(walls, 0.5)

    report = {
        "dataset": dataset, "runs": runs, "run_ids": [m["run_id"] for m in manifests],
        "statuses": [m["status"] for m in manifests],
        "provider": manifests[0].get("provider"), "git_commit": manifests[0].get("git_commit"),
        "config_sha256": manifests[0].get("config_sha256"),
        "end_to_end_seconds": {"p50": p50_wall, "p95": _pct(walls, 0.95), "all": walls},
        "per_stage_seconds": per_stage,
        "llm": {
            "cold_run_llm_seconds": sum(llm[0].values()),
            "cached_runs_llm_seconds_p50": _pct([sum(x.values()) for x in llm[1:]], 0.5) if runs > 1 else None,
            "cold_run_by_stage": llm[0],
            "calls_and_cache_hits": [{"calls": c, "cache_hits": h} for c, h in calls],
            "cold_wall_seconds": walls[0],
            "cached_wall_seconds_p50": _pct(walls[1:], 0.5) if runs > 1 else None,
        },
        "reproducible": bool(fps[0]) and all(f == fps[0] for f in fps),
        "fingerprints": fps[0],
        "resume": {"from": resume_from, "wall_seconds": resume_wall, "status": resumed["status"],
                   "full_run_p50_seconds": p50_wall,
                   "saved_pct": round(100 * (1 - resume_wall / p50_wall), 1) if p50_wall else None},
        "manual_baseline": base,
    }
    if base and base.get("measured") and p50_wall:
        report["manual_vs_automated"] = {"manual_minutes": base["minutes_total"], "automated_minutes": round(p50_wall / 60, 2),
                                         "ratio": round(base["minutes_total"] * 60 / p50_wall, 1)}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")
    report["report_dir"] = str(out_dir)
    return report


def to_markdown(r: dict[str, Any]) -> str:
    e, l, rs = r["end_to_end_seconds"], r["llm"], r["resume"]
    lines = [
        f"# BIFlow benchmark: {r['dataset']} ({r['runs']} runs)",
        "",
        f"Commit `{r['git_commit']}`, provider `{r['provider']}`, config sha256 `{(r['config_sha256'] or '')[:12]}`. "
        f"Statuses: {', '.join(r['statuses'])}.",
        "",
        "## End to end",
        "",
        "| metric | value |", "|---|---|",
        f"| end-to-end p50 | {e['p50']} s |", f"| end-to-end p95 | {e['p95']} s |",
        f"| cold run (empty LLM cache) | {l['cold_wall_seconds']} s, of which LLM {l['cold_run_llm_seconds']:.2f} s |",
        f"| cached runs p50 | {l['cached_wall_seconds_p50']} s, of which LLM {l['cached_runs_llm_seconds_p50']} s |",
        f"| `--resume --from {rs['from']}` | {rs['wall_seconds']} s ({rs['saved_pct']}% less than a full run) |",
        f"| reproducible (mart fingerprints identical in every run) | {'yes' if r['reproducible'] else 'NO'} |",
    ]
    if mv := r.get("manual_vs_automated"):
        lines.append(f"| manual baseline vs automated | {mv['manual_minutes']} min vs {mv['automated_minutes']} min (x{mv['ratio']}) |")
    else:
        lines.append("| manual baseline vs automated | not measured yet (docs/manual_baseline.yaml) |")
    lines += ["", "## Per stage (seconds)", "", "| stage | source | p50 | p95 |", "|---|---|---|---|"]
    for s, v in r["per_stage_seconds"].items():
        lines.append(f"| {s} | {v['source']} | {v['p50']} | {v['p95']} |")
    lines += ["", "LLM seconds by stage in the cold run: " + (", ".join(f"{k} {v}" for k, v in l["cold_run_by_stage"].items()) or "none"), ""]
    return "\n".join(lines)
