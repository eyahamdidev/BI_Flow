"""Completeness: every step registered by the other modules must have at least one event."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .constants import AUDITOR_STEPS, MODULE_PORTS, STATIC_LINEAGE_STEPS


def _flatten(registry: dict[str, list[str]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for module in STATIC_LINEAGE_STEPS:
        for step in registry.get(module, []):
            if step not in seen:
                seen.add(step)
                ordered.append(step)
    for steps in registry.values():
        for step in steps:
            if step not in seen and step not in AUDITOR_STEPS:
                seen.add(step)
                ordered.append(step)
    return ordered


def registered_steps(options: dict[str, Any] | None = None) -> tuple[list[str], str]:
    """Return (step names, source). Source is options, meta, or static."""
    options = options or {}
    if options.get("registered_steps"):
        return [str(step) for step in options["registered_steps"]], "options"
    if options.get("offline_registry"):
        return _flatten(STATIC_LINEAGE_STEPS), "static"
    live: dict[str, list[str]] = {}
    for module in STATIC_LINEAGE_STEPS:
        url = os.getenv(f"URL_{module.upper()}", f"http://localhost:{MODULE_PORTS[module]}")
        try:
            response = httpx.get(f"{url}/v1/meta", timeout=httpx.Timeout(0.4, connect=0.2))
            response.raise_for_status()
            live[module] = [str(step) for step in response.json().get("lineage_steps") or []]
        except (httpx.HTTPError, ValueError, OSError):
            return _flatten(STATIC_LINEAGE_STEPS), "static"
    return _flatten(live), "meta"


def completeness(events: list[dict[str, Any]], options: dict[str, Any] | None = None) -> dict[str, Any]:
    registered, source = registered_steps(options)
    observed: list[str] = []
    seen: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("agent") == "auditor" or event.get("step") in AUDITOR_STEPS:
            continue
        step = event.get("step")
        if step and step not in seen:
            seen.add(str(step))
            observed.append(str(step))
    untracked = [step for step in registered if step not in seen]
    coverage = 1.0 if not registered else (len(registered) - len(untracked)) / len(registered)
    return {
        "source": source,
        "registered_steps": registered,
        "observed_steps": observed,
        "untracked_transformations": untracked,
        "registered_count": len(registered),
        "observed_count": len(registered) - len(untracked),
        "untracked_count": len(untracked),
        "coverage": round(coverage, 4),
        "coverage_pct": round(coverage * 100, 1),
    }
