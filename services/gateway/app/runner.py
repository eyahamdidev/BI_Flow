"""Pipeline runner (BO1). The ONLY component that calls modules.

The pipeline is a LangGraph state graph built from graph.yaml:

    START -> ingest -> validate_raw -> profile -> ... -> analyse -> dashboard_config -> lineage_graph -> audit -> summarize -> END
                 \\________ on failure: jump to the first `always: true` stage (the Auditor explains the failure) ____/

Every stage node POSTs a RunRequest to its module (retries 2x), appends the returned lineage_events to
data/runs/<run_id>/lineage/events.jsonl (only the gateway writes lineage) and saves run_manifest.json, so
`--resume` continues at the first stage that is not ok.

Inputs passed to each module = every artifact produced so far, keyed "<stage>.<artifact name>" (paths relative to
DATA_DIR). Modules pick what they need. Data is never sent inline.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import httpx
import yaml
from langgraph.graph import END, START, StateGraph

DEFAULT_PORTS = {"etl": 8101, "auditor": 8102, "profile_clean": 8103, "ingest_quality": 8104, "semantic_kpi": 8105, "analyst": 8106}
RETRIES = 2
SUMMARY_NODE = "summarize"


# ---------------------------------------------------------------- small helpers
def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def module_url(module: str) -> str:
    return os.getenv(f"URL_{module.upper()}", f"http://localhost:{DEFAULT_PORTS[module]}")


def load_graph() -> list[dict[str, Any]]:
    return yaml.safe_load((Path(__file__).parent / "graph.yaml").read_text())["stages"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _git_commit() -> str | None:
    """Short commit hash. Uses `git` if installed, else reads the .git files directly (the container has no git)."""
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        git_dir = Path(os.getenv("GIT_DIR", ".git"))
        head = (git_dir / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head[:7]  # detached HEAD holds the hash itself
        ref = head[5:]
        ref_file = git_dir / ref
        if ref_file.exists():
            return ref_file.read_text().strip()[:7]
        for line in (git_dir / "packed-refs").read_text().splitlines():  # refs packed by `git gc`
            if line.endswith(" " + ref):
                return line.split()[0][:7]
    except Exception:  # noqa: BLE001
        pass
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


def _append_events(run_dir: Path, events: list[dict[str, Any]]) -> None:
    with (run_dir / "lineage" / "events.jsonl").open("a") as f:  # ONLY the gateway writes lineage
        for e in events:
            f.write(json.dumps(e) + "\n")


def _gateway_event(run_id: str, step: str, **kw: Any) -> dict[str, Any]:
    return {"event_id": str(uuid.uuid4()), "run_id": run_id, "ts": _now(), "agent": "gateway", "step": step,
            "method": "deterministic", **kw}


def repo_root() -> Path:
    """Folder holding configs/ (repo root locally, /srv in the container)."""
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "configs" / "datasets").is_dir():
            return p
    return Path.cwd().resolve()


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_dataset_config(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Read a dataset YAML, resolving `extends: other.yaml` (deep merge, child wins; chains allowed)."""
    if path in _seen:
        raise ValueError(f"circular `extends`: {' -> '.join(map(str, (*_seen, path)))}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    parent = cfg.pop("extends", None)
    if parent:
        cfg = _deep_merge(load_dataset_config((path.parent / parent).resolve(), (*_seen, path)), cfg)
    return cfg


def freeze_config(dataset: str, config_ref: str | None, run_dir: Path) -> tuple[str, str]:
    """Resolve the dataset config ONCE per run and freeze it in the run folder. Every module reads the frozen copy,
    so a run is reproducible even if configs/ changes later. Returns (config_ref for modules, sha256)."""
    frozen = run_dir / "dataset.yaml"
    if not frozen.exists():
        src = repo_root() / (config_ref or f"configs/datasets/{dataset}.yaml")
        cfg = load_dataset_config(src.resolve())
        frozen.write_text(f"# frozen by the gateway from {src.relative_to(repo_root())} (extends resolved). Do not edit.\n"
                          + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    ref = frozen.resolve().relative_to(repo_root()).as_posix() if frozen.resolve().is_relative_to(repo_root()) else str(frozen)
    return ref, _sha256(frozen)


def new_manifest(run_id: str, dataset: str) -> dict[str, Any]:
    return {
        "run_id": run_id, "dataset": dataset, "created": _now(), "git_commit": _git_commit(),
        "provider": os.getenv("LLM_PROVIDER", "ollama"), "profile": os.getenv("BIFLOW_PROFILE"),
        "embed_provider": os.getenv("EMBED_PROVIDER", "ollama"),
        "status": "running", "modules": {},
        "stages": {s["name"]: {"status": "pending"} for s in load_graph()},
        "artifacts": {}, "warnings": [],
    }


def module_health(client: httpx.Client, modules: set[str]) -> dict[str, dict[str, Any]]:
    """Ask every module whether it is up and mocked, so the manifest says honestly which results are real.
    Uses /v1/meta (contract field `mock`), not /health: a module's /health may probe its LLM and be slow."""
    out = {}
    for m in sorted(modules):
        try:
            h = client.get(f"{module_url(m)}/v1/meta", timeout=10).json()
            out[m] = {"up": True, "mock": bool(h.get("mock")), "contract_version": h.get("contract_version"),
                      "lineage_steps": h.get("lineage_steps") or []}
        except Exception:  # noqa: BLE001
            out[m] = {"up": False, "mock": None}
    return out


def call_module(client: httpx.Client, stage: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    r = client.post(f"{module_url(stage['module'])}/v1/run", json=req, timeout=stage.get("timeout_s", 60))
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {"status": "error", "error": {"code": "INTERNAL", "message": f"non-JSON response HTTP {r.status_code}"}}


def seed_ingest(manifest: dict[str, Any], run_dir: Path, source_run: str) -> None:
    """DEV: reuse the 00_ingest parquet of an earlier run (e.g. one made by scripts/dev_seed_run.py) instead of
    calling the ingest module. Recorded as a seeded stage + lineage event, so the run never pretends it ingested."""
    src = data_dir() / "runs" / source_run / "00_ingest"
    files = sorted(src.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"--ingest-from {source_run}: no parquet in {src}")
    dst = run_dir / "00_ingest"
    dst.mkdir(parents=True, exist_ok=True)
    outputs = []
    for f in files:
        shutil.copy2(f, dst / f.name)
        rel = f"runs/{manifest['run_id']}/00_ingest/{f.name}"
        manifest["artifacts"][f"ingest.{f.stem}"] = rel
        outputs.append({"name": f.stem, "path": rel, "sha256": _sha256(dst / f.name)})
    manifest["stages"]["ingest"] = {"status": "ok", "seeded_from": source_run, "seconds": 0.0, "mock": False,
                                    "metrics": {"tables": len(files)}}
    _append_events(run_dir, [_gateway_event(manifest["run_id"], "seed_ingest", rule=f"copy runs/{source_run}/00_ingest",
                                            inputs=[{"name": source_run}], outputs=outputs, rows_affected=None)])


# ---------------------------------------------------------------- the graph
class PipelineState(TypedDict):
    manifest: dict[str, Any]
    failed: bool


class _Ctx:
    """What every node needs but that is not pipeline state: paths, HTTP client, run options."""

    def __init__(self, run_dir: Path, config_ref: str, resume: bool, lang: str, client: httpx.Client):
        self.run_dir, self.config_ref, self.resume, self.lang, self.client = run_dir, config_ref, resume, lang, client


def _stage_node(stage: dict[str, Any], ctx: _Ctx):
    def node(state: PipelineState) -> PipelineState:
        manifest = state["manifest"]
        st = manifest["stages"].setdefault(stage["name"], {"status": "pending"})
        if st["status"] == "ok" and (ctx.resume or st.get("seeded_from")):
            return state  # done in an earlier attempt (or seeded): keep it

        options = dict(stage.get("options", {}))
        if stage["module"] == "auditor":
            # Rule 2: modules never call each other. The Auditor's completeness check needs every module's registered
            # lineage steps; the gateway already read them from /v1/meta, so it passes them instead.
            options.setdefault("registered_steps", sorted({
                step for mod, info in manifest["modules"].items() if mod != "auditor" for step in info.get("lineage_steps", [])
            }))
        req = {
            "request_id": str(uuid.uuid4()), "run_id": manifest["run_id"], "dataset": manifest["dataset"],
            "mode": stage["mode"], "config_ref": ctx.config_ref, "inputs": dict(manifest["artifacts"]),
            "options": options, "lang": ctx.lang,
        }
        st.clear()
        st.update(status="running", started=_now(), module=stage["module"],
                  mock=manifest["modules"].get(stage["module"], {}).get("mock"))
        resp: dict[str, Any] = {}
        t0 = time.perf_counter()
        for attempt in range(RETRIES + 1):
            try:
                resp = call_module(ctx.client, stage, req)
            except httpx.HTTPError as e:
                resp = {"status": "error", "error": {"code": "TIMEOUT", "message": f"{type(e).__name__}: {e}"}}
            if resp.get("status") in ("ok", "partial"):
                break
            if (resp.get("error") or {}).get("code") in ("BAD_INPUT", "SCHEMA_MISMATCH"):
                break  # the same input will fail the same way: do not waste retries
            time.sleep(min(2 ** attempt, 4))
        st["seconds"] = round(time.perf_counter() - t0, 2)
        st["attempts"] = attempt + 1
        st["finished"] = _now()

        failed = state["failed"]
        if resp.get("status") in ("ok", "partial"):
            # Trust but verify: a module that says "ok" must have written every output it declares.
            # (mocks are exempt: they return canned paths without writing files)
            missing = [] if st.get("mock") else [a["path"] for a in resp.get("outputs", []) if not (data_dir() / a["path"]).exists()]
            if missing:
                resp = {**resp, "status": "error", "error": {
                    "code": "INTERNAL", "message": f"module answered {resp['status']} but declared outputs are missing: {missing[:3]}"}}
        if resp.get("status") in ("ok", "partial"):
            st["status"] = resp["status"]
            st["metrics"] = resp.get("metrics", {})
            st["llm_calls"] = resp.get("llm_calls", [])
            manifest["warnings"] += [f"{stage['name']}: {w}" for w in resp.get("warnings", [])]
            for a in resp.get("outputs", []):
                a["sha256"] = a.get("sha256") or _sha256(data_dir() / a["path"])  # gateway verifies what it can
                manifest["artifacts"][f"{stage['name']}.{a['name']}"] = a["path"]
            _append_events(ctx.run_dir, resp.get("lineage_events", []))
        else:
            st["status"] = "failed"
            st["error"] = resp.get("error")
            _append_events(ctx.run_dir, resp.get("lineage_events", []))  # a failing module may still explain itself
            failed = True
        _save(ctx.run_dir, manifest)
        return {"manifest": manifest, "failed": failed}

    return node


def _summary_node(ctx: _Ctx):
    def node(state: PipelineState) -> PipelineState:
        from .summary import summarize

        m = state["manifest"]
        for st in m["stages"].values():
            if st["status"] in ("pending", "running"):
                st["status"] = "skipped"  # jumped over after a failure
        m["status"] = "failed" if any(s["status"] == "failed" for s in m["stages"].values()) else "ok"
        m["finished"] = _now()
        m["total_seconds"] = round(sum(s.get("seconds") or 0 for s in m["stages"].values()), 2)
        try:
            s = summarize(m, ctx.lang)
        except Exception as e:  # noqa: BLE001  the summary must never break a run
            s = {"text": f"(summary unavailable: {type(e).__name__})", "source": "error", "facts": {}, "llm_calls": [], "fact_check": str(e)}
        (ctx.run_dir / "run_summary.md").write_text(s["text"] + "\n", encoding="utf-8")
        m["summary"] = {"text": s["text"], "source": s["source"], "fact_check": s["fact_check"], "llm_calls": s["llm_calls"]}
        m["artifacts"]["summary.run_summary"] = f"runs/{m['run_id']}/run_summary.md"
        _append_events(ctx.run_dir, [_gateway_event(
            m["run_id"], "run_summary", rule="fact sheet -> paragraph; numbers fact-checked",
            method="llm_assisted" if s["source"] == "llm" else "deterministic",
            params={"source": s["source"], "fact_check": s["fact_check"], "facts": s["facts"]},
            llm=(s["llm_calls"][-1] if s["llm_calls"] else None))])
        _save(ctx.run_dir, m)
        return {"manifest": m, "failed": state["failed"]}

    return node


def build_graph(ctx: _Ctx | None = None):
    """Compile graph.yaml into a LangGraph StateGraph. ctx=None builds it for drawing only."""
    stages = load_graph()
    names = [s["name"] for s in stages]
    g = StateGraph(PipelineState)
    for s in stages:
        g.add_node(s["name"], _stage_node(s, ctx) if ctx else (lambda st: st))
    g.add_node(SUMMARY_NODE, _summary_node(ctx) if ctx else (lambda st: st))
    g.add_edge(START, names[0])

    for i, name in enumerate(names):
        nxt = names[i + 1] if i + 1 < len(names) else SUMMARY_NODE
        # where to go after a failure: the next `always` stage (Auditor), else straight to the summary
        jump = next((s["name"] for s in stages[i + 1:] if s.get("always")), SUMMARY_NODE)
        if nxt == jump:
            g.add_edge(name, nxt)
        else:
            def route(state: PipelineState, nxt: str = nxt, jump: str = jump) -> str:
                return jump if state["failed"] else nxt
            g.add_conditional_edges(name, route, {nxt: nxt, jump: jump})
    g.add_edge(SUMMARY_NODE, END)
    return g.compile()


def run_pipeline(dataset: str, run_id: str | None = None, resume: bool = False, config_ref: str | None = None,
                 ingest_from: str | None = None, lang: str = "en", rerun_from: str | None = None) -> dict[str, Any]:
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    run_dir = data_dir() / "runs" / run_id
    (run_dir / "lineage").mkdir(parents=True, exist_ok=True)
    mf_path = run_dir / "run_manifest.json"
    manifest = json.loads(mf_path.read_text()) if (resume and mf_path.exists()) else new_manifest(run_id, dataset)
    manifest["status"] = "running"
    if resume and rerun_from:  # `--from STAGE`: redo that stage and everything after it, keep what came before
        names = [s["name"] for s in load_graph()]
        if rerun_from not in names:
            raise ValueError(f"unknown stage '{rerun_from}'; stages: {names}")
        for n in names[names.index(rerun_from):]:
            manifest["stages"][n] = {"status": "pending"}
    config_ref, manifest["config_sha256"] = freeze_config(dataset, config_ref, run_dir)
    manifest["config_ref"] = config_ref

    with httpx.Client() as client:
        manifest["modules"] = module_health(client, {s["module"] for s in load_graph()})
        if ingest_from and manifest["stages"].get("ingest", {}).get("status") != "ok":
            seed_ingest(manifest, run_dir, ingest_from)
        _save(run_dir, manifest)
        ctx = _Ctx(run_dir, config_ref, resume, lang, client)
        failed = any(s["status"] == "failed" for s in manifest["stages"].values()) and not resume
        final = build_graph(ctx).invoke({"manifest": manifest, "failed": failed}, {"recursion_limit": 100})
    return final["manifest"]


def explain(run_id: str, kpi_id: str, period: str, compare_to: str | None = None) -> dict[str, Any]:
    """Gateway gathers file refs, Auditor writes the answer (spec BO2 step 4)."""
    mf = json.loads((data_dir() / "runs" / run_id / "run_manifest.json").read_text())
    req = {
        "request_id": str(uuid.uuid4()), "run_id": run_id, "dataset": mf["dataset"], "mode": "explain",
        "inputs": mf["artifacts"], "options": {"kpi_id": kpi_id, "period": period, "compare_to": compare_to}, "lang": "en",
    }
    with httpx.Client() as client:
        return call_module(client, {"module": "auditor", "timeout_s": 45}, req)


def ask(run_id: str, question: str) -> dict[str, Any]:
    """Plain-language question -> KPI id (BO5 map_question: retrieval + optional LLM pick). Used by the dashboard."""
    mf = json.loads((data_dir() / "runs" / run_id / "run_manifest.json").read_text())
    req = {
        "request_id": str(uuid.uuid4()), "run_id": run_id, "dataset": mf["dataset"], "mode": "map_question",
        "config_ref": mf.get("config_ref"), "inputs": mf["artifacts"], "options": {"question": question}, "lang": "en",
    }
    with httpx.Client() as client:
        return call_module(client, {"module": "semantic_kpi", "timeout_s": 30}, req)


def list_datasets() -> list[dict[str, Any]]:
    """Datasets that can be run: one per configs/datasets/<name>.yaml (drafts from uploads excluded)."""
    out = []
    for f in sorted((repo_root() / "configs" / "datasets").glob("*.yaml")):
        if f.stem.startswith("uploaded_"):
            continue
        try:
            cfg = load_dataset_config(f)
        except Exception:  # noqa: BLE001  a broken config is listed as unavailable, not hidden
            out.append({"name": f.stem, "available": False, "note": "config could not be read"})
            continue
        src = cfg.get("source") or {}
        files = list((src.get("tables") or {}).values())
        folder = repo_root() / str(src.get("path", ""))
        present = sum((folder / x).exists() for x in files)
        out.append({"name": f.stem, "domain": cfg.get("domain"), "tables": len(files), "available": present == len(files),
                    "note": "" if present == len(files) else f"data missing in {src.get('path')} ({present}/{len(files)} files)"})
    return out
