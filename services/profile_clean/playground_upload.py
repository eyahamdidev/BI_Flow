"""Upload flow UI and pipeline for playground."""
from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml
from app.column_roles import infer_table_roles
from app.decisions_store import load_decisions_file, save_decisions_file
from app.invariants import check_cleaning_invariants
from draft_yaml import generate_draft_yaml, validate_yaml_structure, yaml_dump
from report_pdf import persist_run_snapshot
from report_ui import render_report_section
from upload_parse import (
    ParseSettings,
    read_upload_bytes,
    sanitize_filename,
    slugify,
    write_ingest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _llm_provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama")


def save_upload_originals(dataset: str, files: list[tuple[str, bytes]], data_dir: Path) -> list[Path]:
    dest = data_dir / "uploads" / dataset
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for name, content in files:
        safe = sanitize_filename(name)
        target = dest / safe
        if target.exists():
            target = dest / f"{target.stem}_{uuid.uuid4().hex[:6]}{target.suffix}"
        target.write_bytes(content)
        saved.append(target)
    return saved


def write_config_files(cfg: dict[str, Any], dataset: str, run_id: str, data_dir: Path) -> str:
    rel = f"configs/datasets/uploaded_{dataset}.yaml"
    abs_repo = REPO_ROOT / rel
    abs_repo.parent.mkdir(parents=True, exist_ok=True)
    text = yaml_dump(cfg)
    abs_repo.write_text(text, encoding="utf-8")
    run_copy = data_dir / "runs" / run_id / "config_used.yaml"
    run_copy.parent.mkdir(parents=True, exist_ok=True)
    run_copy.write_text(text, encoding="utf-8")
    return rel


def run_service_pipeline(
    service_url: str,
    run_id: str,
    dataset: str,
    config_ref: str,
    table_paths: list[Path],
    data_dir: Path,
    post_run: Callable[..., tuple[int, float, dict | None, str | None]],
    build_inputs: Callable[..., dict[str, str]],
    llm_off: bool = True,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    inputs = build_inputs(run_id, table_paths)
    if llm_off:
        # Works via YAML llm_advisory.enabled; options ignored by service today
        pass

    for step, mode, options in [
        ("profile_before", "profile", {"stage": "before"}),
        ("clean", "clean", {}),
        ("profile_after", "profile", {"stage": "after", "profile_before_path": f"runs/{run_id}/01_profile/profile.json"}),
    ]:
        if mode == "clean":
            prof = data_dir / f"runs/{run_id}/01_profile/profile.json"
            if prof.exists():
                inputs = {**inputs, "profile": f"runs/{run_id}/01_profile/profile.json"}
        if mode == "profile" and options.get("stage") == "after":
            cl = data_dir / "runs" / run_id / "02_clean"
            inputs = {f"clean.{p.stem}": f"runs/{run_id}/02_clean/{p.name}".replace("\\", "/") for p in cl.glob("*.parquet")}
        body = {
            "request_id": str(uuid.uuid4()),
            "run_id": run_id,
            "dataset": dataset,
            "mode": mode,
            "config_ref": config_ref,
            "inputs": inputs,
            "options": options,
            "lang": "en",
            "trace_parent": None,
        }
        http, rtt, resp, err = post_run(service_url, body)
        results[step] = {"http": http, "rtt": rtt, "resp": resp, "err": err}
        if resp and resp.get("status") == "error":
            break
    return results


def before_after_summary(run_id: str, data_dir: Path) -> list[dict[str, Any]]:
    ing = data_dir / "runs" / run_id / "00_ingest"
    cl = data_dir / "runs" / run_id / "02_clean"
    qlog_p = cl / "quality_log.json"
    qlog = json.loads(qlog_p.read_text(encoding="utf-8")) if qlog_p.exists() else []
    rows: list[dict[str, Any]] = []
    for pq in ing.glob("*.parquet"):
        t = pq.stem
        clean_p = cl / f"{t}.parquet"
        if not clean_p.exists():
            continue
        df_in = pd.read_parquet(pq)
        df_out = pd.read_parquet(clean_p)
        imputed = sum(1 for e in qlog if isinstance(e, dict) and e.get("table") == t and "impute" in str(e.get("rule_id", "")))
        outliers = sum(int(df_out[c].sum()) for c in df_out.columns if c.endswith("__outlier"))
        rows.append(
            {
                "table": t,
                "rows_in": len(df_in),
                "rows_out": len(df_out),
                "nulls_in": int(df_in.isna().sum().sum()),
                "nulls_out": int(df_out.isna().sum().sum()),
                "imputed_ops": imputed,
                "outliers_flagged": outliers,
            }
        )
    return rows


def changed_cells_view(run_id: str, data_dir: Path, table: str, rule_filter: str | None = None) -> pd.DataFrame:
    ing = pd.read_parquet(data_dir / "runs" / run_id / "00_ingest" / f"{table}.parquet")
    cl = pd.read_parquet(data_dir / "runs" / run_id / "02_clean" / f"{table}.parquet")
    changed_cols = [c for c in cl.columns if c in ing.columns and not ing[c].equals(cl[c])]
    if not changed_cols:
        return pd.DataFrame()
    merged = ing.assign(_src="raw").merge(cl.assign(_src="clean"), on=list(ing.columns.intersection(cl.columns)), how="outer", suffixes=("_raw", "_clean"))
    return merged.head(50)


def render_upload_section(
    *,
    repo_data_dir: Callable[[], Path],
    post_run: Callable,
    build_inputs: Callable,
    render_run_result: Callable,
    render_checks: Callable,
    reconcile_from_disk: Callable,
    lineage_steps: list[str],
) -> None:
    st.header("Use my own data")
    slug_preview = slugify(st.session_state.get("upload_dataset", "mydata"))
    prior = load_decisions_file(slug_preview)
    if prior:
        st.info("Decisions from last run will be merged (category maps, NA tokens, overrides).")
    st.caption(f"LLM provider: `{_llm_provider()}` — uploads default LLM **off** in generated YAML.")

    max_mb = st.number_input("Max upload size (MB)", value=200, min_value=1, max_value=500)
    uploaded = st.file_uploader(
        "Upload table files",
        type=["csv", "tsv", "txt", "xlsx", "xls", "json", "jsonl", "parquet", "gz", "zip"],
        accept_multiple_files=True,
    )
    dataset = st.text_input("Dataset name (slug)", value=st.session_state.get("upload_dataset", "mydata"))
    slug = slugify(dataset)
    st.session_state["upload_dataset"] = slug
    if st.session_state.get("_upload_slug") != slug:
        st.session_state["upload_run_id"] = f"upload_{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        st.session_state["_upload_slug"] = slug
    run_id = st.text_input("Run id", value=st.session_state.get("upload_run_id", f"upload_{slug}_"))
    st.session_state["upload_run_id"] = run_id

    parse_opts = ParseSettings(
        encoding=st.selectbox("Encoding override", ["auto", "utf-8", "utf-8-sig", "latin-1", "cp1252"], index=0),
        delimiter=st.selectbox("Delimiter", ["auto", ",", ";", "\\t", "|"], index=0),
        header=not st.checkbox("No header row", value=False),
        dayfirst=st.checkbox("Dates: day-first (dd/mm/yyyy)", value=True),
    )
    if parse_opts.encoding == "auto":
        parse_opts.encoding = ""
    if parse_opts.delimiter == "auto":
        parse_opts.delimiter = "auto"
    elif parse_opts.delimiter == "\\t":
        parse_opts.delimiter = "\t"

    if uploaded:
        total = sum(len(f.getvalue()) for f in uploaded)
        if total > max_mb * 1024 * 1024:
            st.error("Total upload exceeds size limit")
            return
        tables: dict[str, pd.DataFrame] = {}
        reports = []
        for f in uploaded:
            name = slugify(Path(f.name).stem)
            try:
                df, rep = read_upload_bytes(f.getvalue(), name, f.name, parse_opts)
                tables[name] = df
                reports.append(rep)
            except ValueError as e:
                st.error(f"{f.name}: {e}")
        if tables:
            st.subheader("Parse report")
            for rep in reports:
                st.write(
                    f"**{rep.table_name}** ({rep.source_name}): enc={rep.encoding}, sep={repr(rep.delimiter)}, "
                    f"rows={rep.rows}, skipped≈{rep.skipped_lines}, renamed={rep.renamed_columns}"
                )
                for w in rep.warnings:
                    st.warning(w)
                st.dataframe(tables[rep.table_name].head(20), width="stretch")
            if st.button("Ingest to run folder", width="stretch"):
                data_dir = repo_data_dir()
                save_upload_originals(st.session_state["upload_dataset"], [(f.name, f.getvalue()) for f in uploaded], data_dir)
                write_ingest(run_id, data_dir, tables, reports, parse_opts.__dict__)
                st.session_state["upload_tables"] = list(tables.keys())
                st.success(f"Ingested to runs/{run_id}/00_ingest/")
                st.session_state["run_id"] = run_id
                st.session_state["dataset"] = f"uploaded_{st.session_state['upload_dataset']}"

    data_dir = repo_data_dir()
    ing = data_dir / "runs" / run_id / "00_ingest"
    if ing.is_dir() and list(ing.glob("*.parquet")):
        tables = {p.stem: pd.read_parquet(p) for p in ing.glob("*.parquet")}
        prof_path = data_dir / "runs" / run_id / "01_profile" / "profile.json"
        profile = json.loads(prof_path.read_text(encoding="utf-8")) if prof_path.exists() else None

        rec_p = data_dir / "runs" / run_id / "01_profile" / "recognition_report.json"
        if not rec_p.exists():
            rec_p = data_dir / "runs" / run_id / "02_clean" / "recognition_report.json"
        if rec_p.exists():
            st.subheader("Recognition report")
            rec_data = json.loads(rec_p.read_text(encoding="utf-8"))
            st.dataframe(pd.DataFrame(rec_data.get("columns", [])), width="stretch")
            st.download_button(
                "Download recognition_report.json",
                rec_p.read_bytes(),
                "recognition_report.json",
                "application/json",
            )

        st.subheader("Column roles (editable via YAML regenerate)")
        role_rows = []
        for t, df in tables.items():
            for c, info in infer_table_roles(df).items():
                role_rows.append({"table": t, "column": c, "role": info.role, "why": info.why})
        st.dataframe(pd.DataFrame(role_rows), width="stretch")

        st.subheader("Draft dataset YAML")
        null_thr = st.slider("High-null flag threshold %", 30, 90, 60)
        outlier_m = st.selectbox("Outlier method", ["iqr", "mad", "isolation_forest"], index=0)
        allow_knn = st.checkbox("Allow KNN imputation in YAML", value=False)
        allow_dup = st.checkbox("Drop exact duplicates", value=True)
        llm_on = st.checkbox("Enable LLM advisory in YAML", value=False)
        if _llm_provider() == "api" and llm_on:
            st.warning("API provider: column names and sample values may be sent to a third-party LLM endpoint.")
            if not st.checkbox("I understand the privacy implications", value=False):
                llm_on = False
        protect = st.multiselect("Protect columns (never impute)", [c for t in tables for c in tables[t].columns])

        if "upload_yaml_text" not in st.session_state or st.button("Reset YAML to generated", width="stretch"):
            cfg = generate_draft_yaml(
                f"uploaded_{st.session_state['upload_dataset']}",
                tables,
                profile,
                null_threshold=null_thr,
                outlier_method=outlier_m,
                allow_knn=allow_knn,
                allow_drop_dupes=allow_dup,
                llm_enabled=llm_on,
                protect_columns=protect,
            )
            st.session_state["upload_yaml_text"] = yaml_dump(cfg)

        yaml_text = st.text_area("Edit YAML", st.session_state["upload_yaml_text"], height=320)
        st.session_state["upload_yaml_text"] = yaml_text
        if st.button("Validate YAML", width="stretch"):
            try:
                cfg = yaml.safe_load(yaml_text)
                errs = validate_yaml_structure(cfg)
                if errs:
                    st.error("; ".join(errs))
                else:
                    st.success("YAML structure OK")
                    # dry profile call
                    config_ref = write_config_files(cfg, st.session_state["upload_dataset"], run_id, data_dir)
                    st.session_state["config_ref"] = config_ref
            except yaml.YAMLError as e:
                st.error(str(e))

        c1, c2, c3, c4 = st.columns(4)
        prof_b = c1.button("Profile", width="stretch", key="up_prof")
        clean_b = c2.button("Clean", width="stretch", key="up_clean")
        after_b = c3.button("Profile (after)", width="stretch", key="up_after")
        run_all = c4.button("Run everything", width="stretch", key="up_all")
        clean_resp_holder: dict[str, Any] = {}

        def _save_cfg_and_paths() -> tuple[str, list[Path], dict]:
            cfg = yaml.safe_load(st.session_state["upload_yaml_text"])
            ref = write_config_files(cfg, st.session_state["upload_dataset"], run_id, data_dir)
            st.session_state["config_ref"] = ref
            paths = list(ing.glob("*.parquet"))
            return ref, paths, cfg

        svc = st.session_state["service_url"]
        ds_name = f"uploaded_{st.session_state['upload_dataset']}"

        def _do_profile(ref: str, paths: list[Path]) -> dict | None:
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": ds_name,
                "mode": "profile",
                "config_ref": ref,
                "inputs": build_inputs(run_id, paths),
                "options": {"stage": "before"},
                "lang": "en",
            }
            http, rtt, resp, err = post_run(svc, body)
            render_run_result(http, rtt, resp, err, lineage_steps)
            return resp

        def _do_clean(ref: str, paths: list[Path]) -> dict | None:
            inputs = build_inputs(run_id, paths)
            if (data_dir / f"runs/{run_id}/01_profile/profile.json").exists():
                inputs["profile"] = f"runs/{run_id}/01_profile/profile.json"
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": ds_name,
                "mode": "clean",
                "config_ref": ref,
                "inputs": inputs,
                "options": {},
                "lang": "en",
            }
            http, rtt, resp, err = post_run(svc, body)
            render_run_result(http, rtt, resp, err, lineage_steps)
            if resp:
                persist_run_snapshot(data_dir / "runs" / run_id, "clean", resp)
                clean_resp_holder["resp"] = resp
            return resp

        def _do_after(ref: str) -> dict | None:
            cl = data_dir / "runs" / run_id / "02_clean"
            inputs = {f"clean.{p.stem}": f"runs/{run_id}/02_clean/{p.name}".replace("\\", "/") for p in cl.glob("*.parquet")}
            body = {
                "request_id": str(uuid.uuid4()),
                "run_id": run_id,
                "dataset": ds_name,
                "mode": "profile",
                "config_ref": ref,
                "inputs": inputs,
                "options": {"stage": "after", "profile_before_path": f"runs/{run_id}/01_profile/profile.json"},
                "lang": "en",
            }
            http, rtt, resp, err = post_run(svc, body)
            render_run_result(http, rtt, resp, err, lineage_steps)
            if resp:
                persist_run_snapshot(data_dir / "runs" / run_id, "profile_after", resp)
            return resp

        if prof_b or clean_b or after_b or run_all:
            ref, paths, _cfg = _save_cfg_and_paths()
            if prof_b or run_all:
                pr = _do_profile(ref, paths)
                if run_all and pr and pr.get("status") != "error":
                    profile = json.loads((data_dir / f"runs/{run_id}/01_profile/profile.json").read_text(encoding="utf-8"))
                    st.session_state["upload_yaml_text"] = yaml_dump(
                        generate_draft_yaml(
                            ds_name, tables, profile,
                            null_threshold=null_thr, outlier_method=outlier_m,
                            allow_knn=allow_knn, allow_drop_dupes=allow_dup,
                            llm_enabled=llm_on, protect_columns=protect,
                        )
                    )
                    ref, paths, _ = _save_cfg_and_paths()
            if clean_b or run_all:
                cr = _do_clean(ref, paths)
                if run_all and cr and cr.get("status") == "error":
                    st.stop()
            if after_b or run_all:
                _do_after(ref)

        st.subheader("Before / after summary")
        st.dataframe(pd.DataFrame(before_after_summary(run_id, data_dir)), width="stretch")

        cl = data_dir / "runs" / run_id / "02_clean"
        if cl.is_dir():
            compare_rows = []
            all_safe = True
            for pq in ing.glob("*.parquet"):
                t = pq.stem
                raw_df = pd.read_parquet(pq)
                clean_p = cl / f"{t}.parquet"
                if not clean_p.exists():
                    continue
                clean_df = pd.read_parquet(clean_p)
                dropped = len(raw_df) - len(clean_df)
                inv = check_cleaning_invariants(raw_df, clean_df, rows_dropped=dropped, pk_col=raw_df.columns[0])
                all_safe = all_safe and not inv
                for c in raw_df.columns:
                    if c not in clean_df.columns:
                        continue
                    changed = int((raw_df[c].astype(str) != clean_df[c].astype(str)).sum()) if len(raw_df) == len(clean_df) else -1
                    dtype_ok = str(raw_df[c].dtype) == str(clean_df[c].dtype)
                    compare_rows.append(
                        {
                            "column": c,
                            "dtype_before": str(raw_df[c].dtype),
                            "dtype_after": str(clean_df[c].dtype),
                            "nulls_before": int(raw_df[c].isna().sum()),
                            "nulls_after": int(clean_df[c].isna().sum()),
                            "values_changed": changed,
                            "dtype_ok": dtype_ok,
                        }
                    )
            if compare_rows:
                st.subheader("Compare raw vs cleaned")
                st.dataframe(pd.DataFrame(compare_rows), width="stretch")
                if all_safe:
                    st.success("Safety verdict: invariants OK on this run")
                else:
                    st.error(f"Safety verdict: issues — {inv}")

        rq_p = data_dir / "runs" / run_id / "02_clean" / "review_queue.json"
        if rq_p.exists():
            st.subheader("Review queue")
            rq = json.loads(rq_p.read_text(encoding="utf-8"))
            st.dataframe(pd.DataFrame(rq), width="stretch")
            if st.button("Approve all category maps to decisions.yaml", key="approve_maps"):
                dec = load_decisions_file(st.session_state["upload_dataset"])
                maps = dec.get("category_maps", {})
                for item in rq:
                    if item.get("proposed_mapping"):
                        maps[f"{item['table']}.{item['column']}"] = item["proposed_mapping"]
                dec["category_maps"] = maps
                save_decisions_file(st.session_state["upload_dataset"], dec)
                st.success("Saved category maps for next run.")

        st.subheader("Downloads")
        cl = data_dir / "runs" / run_id / "02_clean"
        for pq in cl.glob("*.parquet"):
            df = pd.read_parquet(pq)
            csv_bytes = df.to_csv(index=False).encode("utf-8")
            st.download_button(f"CSV {pq.stem}", csv_bytes, f"{pq.stem}_clean.csv", "text/csv")
            st.download_button(f"Parquet {pq.stem}", pq.read_bytes(), f"{pq.stem}_clean.parquet")

        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
            for pq in cl.glob("*.parquet"):
                zf.write(pq, pq.name)
        st.download_button("Zip all cleaned tables", zbuf.getvalue(), "cleaned_tables.zip", "application/zip")

        render_report_section(
            data_dir=data_dir,
            run_id=run_id,
            dataset_slug=st.session_state["upload_dataset"],
            on_clean_response=clean_resp_holder.get("resp") if cl.is_dir() else None,
        )

        render_checks(reconcile_from_disk(run_id))
