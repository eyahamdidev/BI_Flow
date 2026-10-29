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


def datasets() -> list[dict]:
    """Datasets that can be run (from configs/datasets/ on the gateway), with whether their data is present."""
    try:
        r = httpx.get(f"{BASE}/api/datasets", timeout=10)
        return r.json() if r.status_code == 200 else []
    except httpx.HTTPError:
        return []


def template(base: str) -> dict:
    """Files and columns a new dataset needs to reuse `base`'s structure."""
    try:
        r = httpx.get(f"{BASE}/api/datasets/{base}/template", timeout=10)
        return r.json() if r.status_code == 200 else {}
    except httpx.HTTPError:
        return {}


def add_dataset(name: str, base: str, files: list) -> dict:
    """Send uploaded CSVs (Streamlit UploadedFile objects) to the gateway, which checks and saves them."""
    import base64

    payload = {"name": name, "base": base,
               "files": [{"name": f.name, "content_b64": base64.b64encode(f.getvalue()).decode()} for f in files]}
    try:
        r = httpx.post(f"{BASE}/api/datasets", json=payload, timeout=300)
        return r.json() if r.status_code == 200 else {"ok": False, "errors": [f"gateway answered HTTP {r.status_code}"]}
    except httpx.HTTPError as e:
        return {"ok": False, "errors": [f"gateway not reachable ({type(e).__name__})"]}
