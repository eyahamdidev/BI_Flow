"""BO3 profile_clean — local Streamlit playground (HTTP client only, no app imports). Port 8503."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st

# --- paths (repo root = parents[2]: profile_clean -> services -> BI_Flow) ---
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = Path(os.getenv("DATA_DIR", REPO_ROOT / "data")).resolve()
FIXTURE_MINI = Path(__file__).resolve().parent / "tests" / "fixtures" / "olist_mini"
RAW_OLIST = REPO_ROOT / "data" / "raw" / "olist"

RESPONSE_KEYS = {
    "request_id",
    "run_id",
    "module",
    "status",
    "outputs",
    "metrics",
    "warnings",
    "lineage_events",
    "llm_calls",
    "latency_ms",
}
ARTIFACT_KEYS = {"name", "kind", "path", "rows", "sha256", "label"}
LINEAGE_KEYS = {
    "event_id",
    "run_id",
    "ts",
    "agent",
    "step",
    "inputs",
    "outputs",
    "rule",
    "rows_affected",
    "method",
    "params",
}
VALID_METHODS = {"deterministic", "ml", "llm_assisted"}
VALID_STATUS = {"ok", "partial", "error"}


def _init_state() -> None:
    defaults = {
        "service_url": os.getenv("PLAYGROUND_SERVICE_URL", "http://localhost:8103"),
        "data_dir": os.getenv("DATA_DIR", str(DEFAULT_DATA)),
        "dataset": "olist",
        "config_ref": "configs/datasets/olist.yaml",
        "lang": "en",
        "run_id": "demo1",
        "meta": None,
        "health": None,
        "last_runs": [],
        "selected_tables": [],
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def repo_data_dir() -> Path:
    if "data_dir" in st.session_state:
        return Path(st.session_state["data_dir"]).resolve()
    return Path(os.getenv("DATA_DIR", str(DEFAULT_DATA))).resolve()


def ingest_dir(run_id: str) -> Path:
    return repo_data_dir() / "runs" / run_id / "00_ingest"


def clean_dir(run_id: str) -> Path:
    return repo_data_dir() / "runs" / run_id / "02_clean"


def rel_posix(p: Path, base: Path) -> str:
    return p.relative_to(base).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_demo_parquet(run_id: str, source: str = "fixture") -> int:
    dest = ingest_dir(run_id)
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    if source == "raw" and RAW_OLIST.is_dir():
        for csv in RAW_OLIST.glob("*.csv"):
            name = csv.stem.replace("olist_", "").replace("_dataset", "")
            if name.startswith("product_category"):
                name = "category_translation"
            elif name == "geolocation":
                name = "geolocation"
            df = pd.read_csv(csv, nrows=5000 if "geolocation" in name else None)
            out = dest / f"{name}.parquet"
            df.to_parquet(out, index=False)
            count += 1
        return count
    src = FIXTURE_MINI
    if not src.is_dir():
        return 0
    for pq in src.glob("*.parquet"):
        pd.read_parquet(pq).to_parquet(dest / pq.name, index=False)
        count += 1
    return count


def list_ingest_parquets(run_id: str) -> list[Path]:
    d = ingest_dir(run_id)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.parquet"))


def build_inputs(run_id: str, table_paths: list[Path], extra: dict[str, str] | None = None, base: Path | None = None) -> dict[str, str]:
    base = base or repo_data_dir()
    out: dict[str, str] = {}
    for p in table_paths:
        key = p.stem
        out[f"ingest.{key}"] = rel_posix(p, base)
    if extra:
        out.update(extra)
    return out


def post_run(
    service_url: str,
    body: dict[str, Any],
    timeout: float = 130.0,
) -> tuple[int, float, dict[str, Any] | None, str | None]:
    t0 = time.perf_counter()
    try:
        r = httpx.post(f"{service_url.rstrip('/')}/v1/run", json=body, timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        try:
            return r.status_code, ms, r.json(), None
        except Exception:
            return r.status_code, ms, None, r.text[:2000]
    except Exception as e:
        return 0, (time.perf_counter() - t0) * 1000, None, str(e)


def validate_contract(resp: dict[str, Any]) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    allowed = RESPONSE_KEYS | {"error"}
    keys_ok = RESPONSE_KEYS.issubset(resp.keys()) and set(resp.keys()).issubset(allowed)
    checks.append(("Response top-level keys", keys_ok, f"keys={sorted(resp.keys())}"))
    mod_ok = resp.get("module") == "profile_clean"
    checks.append(("module == profile_clean", mod_ok, str(resp.get("module"))))
    st_ok = resp.get("status") in VALID_STATUS
    checks.append(("status in ok|partial|error", st_ok, str(resp.get("status"))))
    for i, a in enumerate(resp.get("outputs") or []):
        ok = ARTIFACT_KEYS.issubset(a.keys())
        checks.append((f"Artifact[{i}] keys", ok, str(a.get("name"))))
    for i, ev in enumerate(resp.get("lineage_events") or []):
        ok = LINEAGE_KEYS.issubset(ev.keys()) and ev.get("method") in VALID_METHODS
        checks.append((f"LineageEvent[{i}]", ok, ev.get("step", "")))
    silent = resp.get("metrics", {}).get("silent_deletions")
    if silent is not None:
        checks.append(("metrics.silent_deletions == 0", silent == 0, str(silent)))
    return checks


def validate_artifacts(resp: dict[str, Any], data_dir: Path, lineage_steps: list[str]) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    steps_meta = set(lineage_steps or [])
    for a in resp.get("outputs") or []:
        path = data_dir / a["path"]
        exists = path.exists()
        checks.append((f"File exists: {a['name']}", exists, str(path)))
        if exists and a.get("sha256"):
            match = sha256_file(path) == a["sha256"]
            checks.append((f"sha256 match: {a['name']}", match, a["sha256"][:12]))
    for ev in resp.get("lineage_events") or []:
        step = ev.get("step")
        if step and steps_meta:
            checks.append((f"step in meta: {step}", step in steps_meta, step))
    return checks


def render_checks(checks: list[tuple[str, bool, str]]) -> None:
    for label, ok, detail in checks:
        icon = "✅" if ok else "❌"
        st.markdown(f"{icon} **{label}** — {detail}")


def render_run_result(http: int, rtt_ms: float, resp: dict[str, Any] | None, err: str | None, lineage_steps: list[str]) -> None:
    st.subheader("Run result")
    if err and resp is None:
        st.error(f"Request failed (HTTP {http}): {err}")
        return
    if resp is None:
        st.error("No JSON body")
        return
    st.write(f"HTTP **{http}** | round-trip **{rtt_ms:.0f} ms** | service latency **{resp.get('latency_ms')} ms**")
    st.write(f"**status:** `{resp.get('status')}`")
    if resp.get("error"):
        st.warning(f"error.code={resp['error'].get('code')} — {resp['error'].get('message')}")
    if resp.get("warnings"):
        st.info("Warnings: " + "; ".join(resp["warnings"]))
    contract = validate_contract(resp)
    artifact = validate_artifacts(resp, repo_data_dir(), lineage_steps)
    st.markdown("**Automatic checks**")
    render_checks(contract + artifact)
    tabs = st.tabs(["Metrics", "Artifacts", "Lineage", "LLM calls", "Raw JSON"])
    with tabs[0]:
        st.json(resp.get("metrics") or {})
    with tabs[1]:
        outs = resp.get("outputs") or []
        if not outs:
            st.write("No outputs")
        else:
            names = [o["name"] for o in outs]
            pick = st.selectbox("Artifact", names, key=f"art_{uuid.uuid4().hex[:8]}")
            art = next(o for o in outs if o["name"] == pick)
            fp = repo_data_dir() / art["path"]
            st.code(str(fp))
            if fp.exists():
                if art["kind"] == "json":
                    st.json(json.loads(fp.read_text(encoding="utf-8")))
                elif art["kind"] == "parquet":
                    st.dataframe(pd.read_parquet(fp).head(50), width="stretch")
                elif art["kind"] == "md":
                    st.markdown(fp.read_text(encoding="utf-8"))
                elif art["kind"] == "html":
                    st.components.v1.html(fp.read_text(encoding="utf-8"), height=400, scrolling=True)
                else:
                    st.write(f"Preview not implemented for kind={art['kind']}")
    with tabs[2]:
        evs = resp.get("lineage_events") or []
        if evs:
            st.dataframe(pd.DataFrame(evs), width="stretch")
        else:
            st.write("No lineage events")
    with tabs[3]:
        llm = resp.get("llm_calls") or []
        if llm:
            st.dataframe(pd.DataFrame(llm), width="stretch")
        else:
            st.caption("No LLM calls recorded for this run.")
    with tabs[4]:
        st.json(resp)


def _dropped_logged_by_table(cl: Path) -> tuple[dict[str, int], str]:
    """Rows removed: quality_log (dedupe/drop rules) vs dropped_rows.json — take max per table to avoid double count."""
    from_qlog: dict[str, int] = {}
    from_rows: dict[str, int] = {}
    notes: list[str] = []
    dropped_path = cl / "dropped_rows.json"
    if dropped_path.exists():
        raw = json.loads(dropped_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for row in raw:
                t = row.get("table", "?")
                from_rows[t] = from_rows.get(t, 0) + 1
        else:
            notes.append("dropped_rows.json is not a list")
    qlog = cl / "quality_log.json"
    if qlog.exists():
        for entry in json.loads(qlog.read_text(encoding="utf-8")):
            if not isinstance(entry, dict):
                continue
            t = entry.get("table")
            n = int(entry.get("rows_affected") or 0)
            rid = entry.get("rule_id", "")
            if not t or not n:
                continue
            if rid == "dedupe":
                from_qlog[t] = from_qlog.get(t, 0) + n
            elif rid == "drop_exact_duplicates":
                from_qlog[t] = max(from_qlog.get(t, 0), n)
            elif rid == "null_strategy" and entry.get("strategy") == "drop":
                from_qlog[t] = from_qlog.get(t, 0) + n
    if not dropped_path.exists() and not qlog.exists():
        notes.append("No dropped_rows.json or quality_log.json yet")
    tables = set(from_qlog) | set(from_rows)
    merged = {t: max(from_qlog.get(t, 0), from_rows.get(t, 0)) for t in tables}
    return merged, "; ".join(notes)


def reconcile_from_disk(run_id: str) -> list[tuple[str, bool, str]]:
    ing = ingest_dir(run_id)
    cl = clean_dir(run_id)
    dropped_by_table, parse_note = _dropped_logged_by_table(cl)
    results: list[tuple[str, bool, str]] = []
    if parse_note and not list(cl.glob("*.parquet")):
        results.append(("Parse dropped rows", False, parse_note))
        return results
    for pq in sorted(cl.glob("*.parquet")):
        if pq.parent.name == "_undo":
            continue
        t = pq.stem
        in_p = ing / f"{t}.parquet"
        if not in_p.exists():
            results.append((f"{t} ingest missing", False, str(in_p)))
            continue
        rows_in = len(pd.read_parquet(in_p))
        rows_out = len(pd.read_parquet(pq))
        dropped = dropped_by_table.get(t, 0)
        ok = rows_in - dropped == rows_out
        msg = f"in={rows_in} dropped={dropped} out={rows_out}" + (f" | {parse_note}" if parse_note else "")
        results.append((f"Reconcile {t}", ok, msg))
    return results


def undo_roundtrip(run_id: str, undo_file: Path) -> tuple[bool, str]:
    """Apply undo parquet to cleaned copy and compare to ingest for affected column."""
    cl = clean_dir(run_id)
    ing = ingest_dir(run_id)
    undo = pd.read_parquet(undo_file)
    if "row_id" not in undo.columns or "original_value" not in undo.columns:
        return False, "undo file missing row_id/original_value columns"
    # undo name: {table}__{rule}.parquet
    stem = undo_file.stem
    table = stem.split("__")[0] if "__" in stem else stem
    clean_p = cl / f"{table}.parquet"
    in_p = ing / f"{table}.parquet"
    if not clean_p.exists() or not in_p.exists():
        return False, f"missing clean or ingest for {table}"
    clean_df = pd.read_parquet(clean_p)
    ingest_df = pd.read_parquet(in_p)
    # Guess id column from first undo row_id matching a column
    id_col = None
    for c in clean_df.columns:
        if c in ingest_df.columns and str(clean_df[c].iloc[0]) == str(undo["row_id"].iloc[0]):
            id_col = c
            break
    if id_col is None:
        id_col = clean_df.columns[0]
    # Guess value column from quality log not available here — use product_category_name or first object col changed
    val_col = None
    for c in clean_df.select_dtypes(include=["object", "string"]).columns:
        if c in ingest_df.columns:
            val_col = c
            break
    if val_col is None:
        return False, "could not infer value column for undo check"
    restored = clean_df.copy()
    id_to_orig = dict(zip(undo["row_id"].astype(str), undo["original_value"], strict=False))
    for idx, row in restored.iterrows():
        rid = str(row[id_col])
        if rid in id_to_orig:
            restored.at[idx, val_col] = id_to_orig[rid]
    merged = restored.merge(ingest_df[[id_col, val_col]], on=id_col, suffixes=("_rest", "_ingest"))
    if merged.empty:
        return False, "no overlapping row ids for sample"
    match = (merged[f"{val_col}_rest"] == merged[f"{val_col}_ingest"]) | (
        merged[f"{val_col}_rest"].isna() & merged[f"{val_col}_ingest"].isna()
    )
    ok = bool(match.all())
    return ok, f"checked {len(merged)} rows on {table}.{val_col} via {id_col}"


def profile_diff_view(run_id: str) -> None:
    diff_p = repo_data_dir() / "runs" / run_id / "03_profile_after" / "profile_diff.json"
    if not diff_p.exists():
        st.info("Run Profile (after) to generate profile_diff.json")
        return
    diff = json.loads(diff_p.read_text(encoding="utf-8"))
    st.json(diff)
    md_p = diff_p.with_suffix(".md")
    if md_p.name.endswith(".json"):
        md_p = diff_p.parent / "profile_diff.md"
    if md_p.exists():
        st.markdown(md_p.read_text(encoding="utf-8"))


def render_demo_page(lineage_steps: list[str]) -> None:
    run_id = st.session_state["run_id"]
    ingest = list_ingest_parquets(run_id)
    if not ingest:
        st.warning(f"No parquet in `{ingest_dir(run_id)}`. Load demo data or copy files manually.")
    else:
        st.success(f"Found {len(ingest)} parquet file(s) in 00_ingest")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Load demo data (olist_mini fixture)", width="stretch", key="demo_load_fixture"):
            n = load_demo_parquet(run_id, "fixture")
            st.success(f"Wrote {n} tables")
            st.rerun()
    with c2:
        if RAW_OLIST.is_dir() and st.button("Load demo data (raw CSV sample)", width="stretch", key="demo_load_raw"):
            n = load_demo_parquet(run_id, "raw")
            st.success(f"Wrote {n} tables from CSV")
            st.rerun()

    ingest = list_ingest_parquets(run_id)
    default_sel = [p.stem for p in ingest]
    selected = st.multiselect("Tables to send in inputs", default_sel, default=default_sel)
    table_paths = [ingest_dir(run_id) / f"{s}.parquet" for s in selected if (ingest_dir(run_id) / f"{s}.parquet").exists()]

    disable_llm = st.checkbox(
        "Disable LLM advisory (options.llm_advisory.enabled=false)",
        value=False,
        help="Sent in options; service may ignore unless handler supports it (see Edge cases / docs).",
    )
    extra_json = st.text_area("Extra options JSON", value="{}", height=80)
    try:
        extra_opts = json.loads(extra_json) if extra_json.strip() else {}
    except json.JSONDecodeError as e:
        st.error(f"Invalid extra JSON: {e}")
        extra_opts = {}

    def merge_options(base: dict[str, Any]) -> dict[str, Any]:
        out = {**extra_opts, **base}
        if disable_llm:
            out.setdefault("llm_advisory", {})
            if isinstance(out["llm_advisory"], dict):
                out["llm_advisory"] = {**out["llm_advisory"], "enabled": False}
            else:
                out["llm_advisory"] = {"enabled": False}
        return out

    tab_run, tab_clean, tab_recon, tab_undo, tab_edge, tab_eval = st.tabs(
        ["Runs", "Clean extras", "Reconciliation", "Undo", "Edge cases", "Eval"]
    )

    with tab_run:
        b1, b2, b3 = st.columns(3)
        with b1:
            run_profile_before = st.button("1. Profile (before)", width="stretch")
        with b2:
            run_clean = st.button("2. Clean", width="stretch")
        with b3:
            cleaned = list(clean_dir(run_id).glob("*.parquet"))
            run_profile_after = st.button(
                "3. Profile (after)",
                width="stretch",
                disabled=not any(p for p in cleaned if p.parent.name != "_undo"),
            )

        if run_profile_before and table_paths:
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": st.session_state["dataset"],
                "mode": "profile",
                "config_ref": st.session_state["config_ref"],
                "inputs": build_inputs(run_id, table_paths),
                "options": merge_options({"stage": "before"}),
                "lang": st.session_state["lang"],
                "trace_parent": None,
            }
            http, rtt, resp, err = post_run(st.session_state["service_url"], body)
            st.session_state["last_runs"].append({"label": "profile_before", "http": http, "resp": resp, "err": err})
            render_run_result(http, rtt, resp, err, lineage_steps)

        if run_clean and table_paths:
            prof_rel = f"runs/{run_id}/01_profile/profile.json"
            inputs = build_inputs(
                run_id,
                table_paths,
                extra={"profile": prof_rel} if (repo_data_dir() / prof_rel).exists() else None,
            )
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": st.session_state["dataset"],
                "mode": "clean",
                "config_ref": st.session_state["config_ref"],
                "inputs": inputs,
                "options": merge_options({}),
                "lang": st.session_state["lang"],
                "trace_parent": None,
            }
            http, rtt, resp, err = post_run(st.session_state["service_url"], body)
            st.session_state["last_runs"].append({"label": "clean", "http": http, "resp": resp, "err": err})
            render_run_result(http, rtt, resp, err, lineage_steps)

        if run_profile_after:
            cl = clean_dir(run_id)
            clean_paths = [p for p in cl.glob("*.parquet") if p.parent.name != "_undo"]
            base = repo_data_dir()
            inputs = {f"clean.{p.stem}": rel_posix(p, base) for p in clean_paths}
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": st.session_state["dataset"],
                "mode": "profile",
                "config_ref": st.session_state["config_ref"],
                "inputs": inputs,
                "options": merge_options(
                    {"stage": "after", "profile_before_path": f"runs/{run_id}/01_profile/profile.json"}
                ),
                "lang": st.session_state["lang"],
                "trace_parent": None,
            }
            http, rtt, resp, err = post_run(st.session_state["service_url"], body)
            st.session_state["last_runs"].append({"label": "profile_after", "http": http, "resp": resp, "err": err})
            render_run_result(http, rtt, resp, err, lineage_steps)
            profile_diff_view(run_id)

    with tab_clean:
        cl = clean_dir(run_id)
        for label, fname in [
            ("quality_log", "quality_log.json"),
            ("review_queue", "review_queue.json"),
            ("dropped_rows", "dropped_rows.json"),
        ]:
            p = cl / fname
            st.subheader(label)
            if p.exists():
                st.json(json.loads(p.read_text(encoding="utf-8")))
            else:
                st.caption(f"Missing {p}")

    with tab_recon:
        st.markdown("Independent file-based reconciliation")
        render_checks(reconcile_from_disk(run_id))

    with tab_undo:
        undo_dir = clean_dir(run_id) / "_undo"
        files = sorted(undo_dir.glob("*.parquet")) if undo_dir.is_dir() else []
        if not files:
            st.info("No undo files under 02_clean/_undo/ yet (run Clean on data with value-changing rules).")
        else:
            pick = st.selectbox("Undo file", [str(f.name) for f in files])
            uf = undo_dir / pick
            undo_df = pd.read_parquet(uf)
            st.dataframe(undo_df.head(20), width="stretch")
            if st.button("Run undo round-trip check", width="stretch"):
                ok, msg = undo_roundtrip(run_id, uf)
                render_checks([("Undo round-trip", ok, msg)])

    with tab_edge:
        st.markdown("Send bad requests; expect documented error codes.")
        svc = st.session_state["service_url"]
        if st.button("Path traversal in inputs", width="stretch"):
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": "olist",
                "mode": "clean",
                "config_ref": st.session_state["config_ref"],
                "inputs": {"bad": "../../etc/passwd.parquet"},
                "options": {},
                "lang": "en",
            }
            http, _, resp, err = post_run(svc, body)
            code = (resp or {}).get("error", {}).get("code")
            render_checks([("HTTP 400", http == 400, str(http)), ("error.code BAD_INPUT", code == "BAD_INPUT", str(code))])
        if st.button("Absolute Windows path in inputs", width="stretch"):
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": "olist",
                "mode": "clean",
                "config_ref": st.session_state["config_ref"],
                "inputs": {"bad": "C:/Windows/System32/drivers/etc/hosts.parquet"},
                "options": {},
                "lang": "en",
            }
            http, _, resp, _ = post_run(svc, body)
            code = (resp or {}).get("error", {}).get("code")
            render_checks([("HTTP 400", http == 400, str(http)), ("error.code BAD_INPUT", code == "BAD_INPUT", str(code))])
        if st.button("Unknown mode", width="stretch"):
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": "olist",
                "mode": "__nope__",
                "config_ref": st.session_state["config_ref"],
                "inputs": {},
                "options": {},
                "lang": "en",
            }
            http, _, resp, _ = post_run(svc, body)
            code = (resp or {}).get("error", {}).get("code")
            render_checks([("HTTP 400", http == 400, str(http)), ("error.code BAD_INPUT", code == "BAD_INPUT", str(code))])
        if st.button("Missing input file", width="stretch"):
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": "olist",
                "mode": "clean",
                "config_ref": st.session_state["config_ref"],
                "inputs": {"x": "runs/missing/00_ingest/nope.parquet"},
                "options": {},
                "lang": "en",
            }
            http, _, resp, _ = post_run(svc, body)
            code = (resp or {}).get("error", {}).get("code")
            render_checks([("HTTP 400", http == 400, str(http)), ("error.code BAD_INPUT", code == "BAD_INPUT", str(code))])
        if st.button("Determinism check (Clean x2)", width="stretch"):
            if not table_paths:
                st.error("Select tables and load demo data first")
            else:
                inputs = build_inputs(run_id, table_paths)
                opts = merge_options({})
                hashes: list[dict[str, str]] = []
                for i in range(2):
                    body = {
                        "request_id": str(uuid.uuid4()),
                        "run_id": f"{run_id}-det{i}",
                        "dataset": st.session_state["dataset"],
                        "mode": "clean",
                        "config_ref": st.session_state["config_ref"],
                        "inputs": inputs,
                        "options": opts,
                        "lang": "en",
                    }
                    http, _, resp, err = post_run(svc, body)
                    if resp is None:
                        st.error(err)
                        break
                    row = {}
                    for a in resp.get("outputs") or []:
                        fp = repo_data_dir() / a["path"]
                        if fp.exists():
                            row[a["name"]] = sha256_file(fp)
                    hashes.append(row)
                if len(hashes) == 2:
                    all_keys = set(hashes[0]) | set(hashes[1])
                    checks = []
                    for k in sorted(all_keys):
                        h1, h2 = hashes[0].get(k), hashes[1].get(k)
                        checks.append((f"sha256 {k}", h1 == h2 and h1 is not None, f"{h1[:12] if h1 else None} vs {h2[:12] if h2 else None}"))
                    st.caption("Uses separate run_ids; compares artifact content hashes (ignores request_id/event_id in JSON).")
                    render_checks(checks)

    with tab_eval:
        if st.button("POST /v1/eval", width="stretch"):
            t0 = time.perf_counter()
            try:
                r = httpx.post(f"{st.session_state['service_url']}/v1/eval", timeout=120.0)
                ms = (time.perf_counter() - t0) * 1000
                st.write(f"HTTP {r.status_code} in {ms:.0f} ms")
                st.json(r.json())
            except Exception as e:
                st.error(str(e))


def main() -> None:
    st.set_page_config(page_title="profile_clean playground", layout="wide")
    _init_state()
    st.title("profile_clean playground (BO3)")
    st.caption("HTTP client only — same contract as the gateway. Service port 8103, UI port 8503.")

    page_demo, page_upload = st.tabs(["Built-in demo (Olist)", "My uploads"])

    with st.sidebar:
        st.session_state["service_url"] = st.text_input("Service URL", st.session_state["service_url"])
        st.session_state["data_dir"] = st.text_input("DATA_DIR", st.session_state["data_dir"])
        st.session_state["dataset"] = st.text_input("dataset", st.session_state["dataset"])
        st.session_state["config_ref"] = st.text_input("config_ref", st.session_state["config_ref"])
        st.session_state["lang"] = st.selectbox("lang", ["en", "fr"], index=0 if st.session_state["lang"] == "en" else 1)
        st.session_state["run_id"] = st.text_input("run_id", st.session_state["run_id"])
        if st.button("Check /health and /v1/meta", width="stretch"):
            try:
                h = httpx.get(f"{st.session_state['service_url']}/health", timeout=5.0).json()
                m = httpx.get(f"{st.session_state['service_url']}/v1/meta", timeout=5.0).json()
                st.session_state["health"] = h
                st.session_state["meta"] = m
            except Exception as e:
                st.error(str(e))
        if st.session_state.get("health"):
            st.json(st.session_state["health"])
        if st.session_state.get("meta"):
            st.json(st.session_state["meta"])

    st.session_state["run_id"]
    meta = st.session_state.get("meta") or {}
    lineage_steps = meta.get("lineage_steps") or []

    with page_upload:
        from playground_upload import render_upload_section

        render_upload_section(
            repo_data_dir=repo_data_dir,
            post_run=post_run,
            build_inputs=build_inputs,
            render_run_result=render_run_result,
            render_checks=render_checks,
            reconcile_from_disk=reconcile_from_disk,
            lineage_steps=lineage_steps,
        )

    with page_demo:
        render_demo_page(lineage_steps)


if __name__ == "__main__":
    main()
