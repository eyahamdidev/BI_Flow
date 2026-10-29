"""API layer: the dashboard is a CLIENT of the gateway, never of a module (spec rule 2)."""
from __future__ import annotations

import os

import httpx

BASE = os.getenv("GATEWAY_URL", "http://localhost:8000")


def explain(run_id: str, kpi_id: str, period: str) -> dict | None:
    try:
        r = httpx.post(f"{BASE}/api/explain", json={"run_id": run_id, "kpi_id": kpi_id, "period": period}, timeout=90)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def ask(run_id: str, question: str) -> dict | None:
    try:
        r = httpx.post(f"{BASE}/api/ask", json={"run_id": run_id, "question": question}, timeout=30)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def start_run(dataset: str = "olist") -> str | None:
    try:
        return httpx.post(f"{BASE}/api/runs", json={"dataset": dataset}, timeout=10).json()["run_id"]
    except Exception:  # noqa: BLE001
        return None
