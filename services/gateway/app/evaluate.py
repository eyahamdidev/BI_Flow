"""Evaluation harness (spec BO1 step 7): one command runs every module's POST /v1/eval and renders ONE results table
(the final results page of the report).

    python -m app.cli eval --all            # every module
    python -m app.cli eval --module etl     # one module

Writes data/eval/<timestamp>/results.json and results.md. Each module owns what its eval measures; the harness only
collects. A module that is down, mocked, or has no eval yet is listed as such (never silently skipped).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx

from . import runner


def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out |= _flatten(v, f"{prefix}{k}.")
    elif isinstance(d, (int, float, str, bool)) or d is None:
        out[prefix.rstrip(".")] = d
    else:
        out[prefix.rstrip(".")] = json.dumps(d)[:80]
    return out


def evaluate(modules: list[str] | None = None, timeout_s: float = 600) -> dict[str, Any]:
    modules = modules or sorted(runner.DEFAULT_PORTS)
    results: dict[str, Any] = {}
    with httpx.Client() as client:
        for m in modules:
            try:
                meta = client.get(f"{runner.module_url(m)}/v1/meta", timeout=10).json()
                r = client.post(f"{runner.module_url(m)}/v1/eval", timeout=timeout_s).json()
                results[m] = {"status": r.get("status"), "mock": meta.get("mock"), "metrics": r.get("metrics", {}),
                              "notes": r.get("notes", [])}
            except Exception as e:  # noqa: BLE001
                results[m] = {"status": "unreachable", "mock": None, "metrics": {}, "notes": [f"{type(e).__name__}: {e}"]}
            print(f"  {m:<15} {results[m]['status']}", flush=True)

    out_dir = runner.data_dir() / "eval" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"created": datetime.now().isoformat(timespec="seconds"), "git_commit": runner._git_commit(), "modules": results}
    (out_dir / "results.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out_dir / "results.md").write_text(to_markdown(report), encoding="utf-8")
    report["report_dir"] = str(out_dir)
    return report


def to_markdown(report: dict[str, Any]) -> str:
    lines = [f"# BIFlow evaluation results ({report['created']}, commit `{report['git_commit']}`)", "",
             "| module | status | source | metric | value |", "|---|---|---|---|---|"]
    for m, r in report["modules"].items():
        src = "mock" if r["mock"] else ("real" if r["mock"] is False else "?")
        flat = _flatten(r["metrics"])
        if not flat:
            lines.append(f"| {m} | {r['status']} | {src} | (none) | {'; '.join(r['notes'])[:100]} |")
        for i, (k, v) in enumerate(flat.items()):
            lines.append(f"| {m if i == 0 else ''} | {r['status'] if i == 0 else ''} | {src if i == 0 else ''} | {k} | {v} |")
    return "\n".join(lines) + "\n"
