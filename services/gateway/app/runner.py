"""Pipeline runner (BO1). The ONLY component that calls modules.

Contract: for every stage it POSTs a RunRequest to the module, appends the returned lineage_events to
data/runs/<run_id>/lineage/events.jsonl, records outputs, and persists run_manifest.json after every stage
so `--resume` can continue at the first non-ok stage.

Inputs passed to each module = every artifact produced so far, keyed "<stage>.<artifact name>" (paths are
relative to DATA_DIR). Modules pick what they need. Data is never sent inline.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

DEFAULT_PORTS = {"etl": 8101, "auditor": 8102, "profile_clean": 8103, "ingest_quality": 8104, "semantic_kpi": 8105, "analyst": 8106}
RETRIES = 2


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def module_url(module: str) -> str:
    return os.getenv(f"URL_{module.upper()}", f"http://localhost:{DEFAULT_PORTS[module]}")


def load_graph() -> list[dict[str, Any]]:
    return yaml.safe_load((Path(__file__).parent / "graph.yaml").read_text())["stages"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def _sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _save(run_dir: Path, manifest: dict[str, Any]) -> None:
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))


def new_manifest(run_id: str, dataset: str) -> dict[str, Any]:
    return {
        "run_id": run_id, "dataset": dataset, "created": _now(), "git_commit": _git_commit(),
        "provider": os.getenv("LLM_PROVIDER", "ollama"), "profile": os.getenv("BIFLOW_PROFILE"),
        "embed_provider": os.getenv("EMBED_PROVIDER", "ollama"),
        "mock": os.getenv("BIFLOW_MOCK", "1"), "status": "running",
        "stages": {s["name"]: {"status": "pending"} for s in load_graph()},
        "artifacts": {}, "warnings": [],
    }


def call_module(client: httpx.Client, stage: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    r = client.post(f"{module_url(stage['module'])}/v1/run", json=req, timeout=stage.get("timeout_s", 60))
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {"status": "error", "error": {"code": "INTERNAL", "message": f"non-JSON response HTTP {r.status_code}"}}


def run_pipeline(dataset: str, run_id: str | None = None, resume: bool = False, config_ref: str | None = None) -> dict[str, Any]:
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    run_dir = data_dir() / "runs" / run_id
    (run_dir / "lineage").mkdir(parents=True, exist_ok=True)
    mf_path = run_dir / "run_manifest.json"
    manifest = json.loads(mf_path.read_text()) if (resume and mf_path.exists()) else new_manifest(run_id, dataset)
    config_ref = config_ref or f"configs/datasets/{dataset}.yaml"
    events_path = run_dir / "lineage" / "events.jsonl"
    failed = False

    with httpx.Client() as client:
        for stage in load_graph():
            st = manifest["stages"].setdefault(stage["name"], {"status": "pending"})
            if resume and st["status"] == "ok":
                continue
            if failed and not stage.get("always"):
                st["status"] = "skipped"
                continue

            inputs = dict(manifest["artifacts"])
            req = {
                "request_id": str(uuid.uuid4()), "run_id": run_id, "dataset": dataset, "mode": stage["mode"],
                "config_ref": config_ref, "inputs": inputs, "options": stage.get("options", {}), "lang": "en",
            }
            st.update(status="running", started=_now())
            resp: dict[str, Any] = {}
            t0 = time.perf_counter()
            for attempt in range(RETRIES + 1):
                try:
                    resp = call_module(client, stage, req)
                except httpx.HTTPError as e:
                    resp = {"status": "error", "error": {"code": "TIMEOUT", "message": str(e)}}
                if resp.get("status") in ("ok", "partial"):
                    break
                time.sleep(min(2 ** attempt, 4))
            st["seconds"] = round(time.perf_counter() - t0, 2)
            st["attempts"] = attempt + 1

            if resp.get("status") in ("ok", "partial"):
                st["status"] = "ok" if resp["status"] == "ok" else "partial"
                st["metrics"] = resp.get("metrics", {})
                st["llm_calls"] = resp.get("llm_calls", [])
                manifest["warnings"] += [f"{stage['name']}: {w}" for w in resp.get("warnings", [])]
                for a in resp.get("outputs", []):
                    a["sha256"] = a.get("sha256") or _sha256(data_dir() / a["path"])  # gateway verifies what it can
                    manifest["artifacts"][f"{stage['name']}.{a['name']}"] = a["path"]
                with events_path.open("a") as f:  # ONLY the gateway writes lineage
                    for e in resp.get("lineage_events", []):
                        f.write(json.dumps(e) + "\n")
            else:
                st["status"] = "failed"
                st["error"] = resp.get("error")
                failed = True
            _save(run_dir, manifest)

    manifest["status"] = "failed" if failed else "ok"
    manifest["finished"] = _now()
    _save(run_dir, manifest)
    return manifest


def explain(run_id: str, kpi_id: str, period: str, compare_to: str | None = None) -> dict[str, Any]:
    """Gateway gathers file refs, Auditor writes the answer (spec BO2 step 4)."""
    mf = json.loads((data_dir() / "runs" / run_id / "run_manifest.json").read_text())
    req = {
        "request_id": str(uuid.uuid4()), "run_id": run_id, "dataset": mf["dataset"], "mode": "explain",
        "inputs": mf["artifacts"], "options": {"kpi_id": kpi_id, "period": period, "compare_to": compare_to}, "lang": "en",
    }
    with httpx.Client() as client:
        return call_module(client, {"module": "auditor", "timeout_s": 30}, req)
