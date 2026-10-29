"""Profiler + Cleaner handlers (BO3)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
from biflow_contracts import RunRequest, RunResponse
from biflow_contracts.biflow_llm import drain_calls

from .cleaner_llm import run_llm_advisory
from .cleaner_ml import apply_imputation, apply_outliers
from .cleaner_rules import CleanState, apply_rules
from .cleaning_recognized import (
    apply_auto_review_maps,
    apply_category_maps,
    apply_sentinel_nulls,
    apply_standardise_recognized,
    suggest_category_variants,
)
from .column_roles import roles_from_config
from .config import (
    TIMEOUT_CLEAN_S,
    TIMEOUT_PROFILE_S,
    load_dataset_yaml,
    stage_output_dir,
)
from .decisions_store import merge_decisions
from .errors import BadInputError, ProfileCleanError, ReconciliationError, TimeoutError
from .io_utils import (
    artifact_from_path,
    read_parquet,
    run_dir,
    validate_input_path,
    write_json,
    write_parquet,
)
from .lineage import LineageTracker
from .profiler import optional_html_report, profile_dataset, profile_diff
from .recognizer import build_recognition_report, recognize_dataset
from .reconcile import assert_reconciliation, reconcile_table
from .type_guard import sanitize_string_nulls, snapshot_dtypes

PK_DEFAULTS = {
    "orders": "order_id",
    "order_items": "order_id",
    "order_payments": "order_id",
    "order_reviews": "review_id",
    "customers": "customer_id",
    "products": "product_id",
    "sellers": "seller_id",
    "geolocation": "geolocation_zip_code_prefix",
    "category_translation": "product_category_name",
}


def _pk_map(ds_cfg: dict[str, Any]) -> dict[str, str]:
    out = dict(PK_DEFAULTS)
    out.update(ds_cfg.get("cleaning_rules", {}).get("primary_keys", {}))
    return out


def _load_tables(req: RunRequest, ds_cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    if req.inputs:
        for name, rel in req.inputs.items():
            if not rel.endswith(".parquet"):
                continue
            path = validate_input_path(rel, name)
            if not path.exists():
                raise BadInputError(f"missing input: {rel}")
            table_name = name.split(".")[-1] if "." in name else name
            tables[table_name] = read_parquet(path)
        return tables
    source_tables = ds_cfg.get("source", {}).get("tables", {})
    stage = "00_ingest" if req.mode != "profile" or req.options.get("stage", "before") == "before" else "02_clean"
    if req.mode == "profile" and req.options.get("stage") == "after":
        stage = "02_clean"
    base = run_dir(req.run_id, stage)
    for tname in source_tables:
        p = base / f"{tname}.parquet"
        if p.exists():
            tables[tname] = read_parquet(p)
    if not tables:
        raise BadInputError("no parquet inputs found")
    return tables


def profile(req: RunRequest) -> RunResponse | dict:
    t0 = time.perf_counter()
    warnings: list[str] = []
    try:
        ds_cfg = load_dataset_yaml(req.config_ref, req.dataset)
    except FileNotFoundError as e:
        raise BadInputError(str(e)) from e
    if time.perf_counter() - t0 > TIMEOUT_PROFILE_S:
        raise TimeoutError("profile timeout before start")

    lineage = LineageTracker(req.run_id)
    tables = _load_tables(req, ds_cfg)
    relationships = ds_cfg.get("relationships", [])
    pk_map = _pk_map(ds_cfg)
    pk_lists = {t: [pk_map[t]] for t in pk_map if t in tables}

    slug = req.dataset.replace("uploaded_", "", 1) if req.dataset.startswith("uploaded_") else req.dataset
    ds_cfg = merge_decisions(ds_cfg, slug)
    prof = profile_dataset(tables, relationships, pk_lists, lineage)
    recognitions = recognize_dataset(tables, ds_cfg)
    out_folder = stage_output_dir(req.run_id, "profile", req.options)
    out_path = run_dir(req.run_id, out_folder)
    rel_base = f"runs/{req.run_id}/{out_folder}"

    profile_json = out_path / "profile.json"
    write_json(prof, profile_json)
    rec_path = out_path / "recognition_report.json"
    write_json(build_recognition_report(recognitions), rec_path)

    outputs = [
        artifact_from_path("profile", "json", f"{rel_base}/profile.json"),
        artifact_from_path("recognition_report", "json", f"{rel_base}/recognition_report.json"),
    ]

    html_path = out_path / "profile.html"
    if optional_html_report(tables, str(html_path)):
        outputs.append(artifact_from_path("profile_html", "html", f"{rel_base}/profile.html"))
    else:
        warnings.append("optional HTML profile skipped (ydata-profiling unavailable or failed)")

    if req.options.get("stage") == "after":
        before_path = validate_input_path(
            req.options.get("profile_before_path", f"runs/{req.run_id}/01_profile/profile.json"),
            "profile_before_path",
        )
        if before_path.exists():
            before = json.loads(before_path.read_text(encoding="utf-8"))
            diff, md = profile_diff(before, prof, req.lang)
            write_json(diff, out_path / "profile_diff.json")
            (out_path / "profile_diff.md").write_text(md, encoding="utf-8")
            outputs.extend(
                [
                    artifact_from_path("profile_diff", "json", f"{rel_base}/profile_diff.json"),
                    artifact_from_path("profile_diff_md", "md", f"{rel_base}/profile_diff.md"),
                ]
            )
            lineage.emit("profile_diff", rule="compare(before,after)")

    metrics = {
        "tables": len(tables),
        "columns": sum(len(d.columns) for d in tables.values()),
        "null_cells": sum(int(d.isna().sum().sum()) for d in tables.values()),
        "duplicate_rows": sum(prof["tables"][t]["duplicate_rows"] for t in prof["tables"]),
    }
    return {
        "status": "ok",
        "outputs": outputs,
        "metrics": metrics,
        "warnings": warnings,
        "lineage_events": lineage.events,
        "llm_calls": drain_calls(),
    }


def clean(req: RunRequest) -> RunResponse | dict:
    t0 = time.perf_counter()
    warnings: list[str] = []
    ds_cfg = load_dataset_yaml(req.config_ref, req.dataset)
    slug = req.dataset.replace("uploaded_", "", 1) if req.dataset.startswith("uploaded_") else req.dataset
    ds_cfg = merge_decisions(ds_cfg, slug)
    rules = ds_cfg.get("cleaning_rules", {})
    lineage = LineageTracker(req.run_id)
    state = CleanState()
    state.warnings = warnings

    tables = _load_tables(req, ds_cfg)
    original_dtypes = snapshot_dtypes(tables)
    column_roles = roles_from_config(ds_cfg, tables)
    rows_in = {t: len(df) for t, df in tables.items()}

    profile_data: dict[str, Any] | None = None
    prof_rel = req.inputs.get("profile") or req.options.get("profile_path")
    if prof_rel:
        try:
            profile_data = json.loads(validate_input_path(prof_rel, "profile").read_text(encoding="utf-8"))
        except BadInputError:
            warnings.append("profile input invalid; LLM advisory degraded")

    out_folder = stage_output_dir(req.run_id, "clean", req.options)
    out_path = run_dir(req.run_id, out_folder)
    rel_base = f"runs/{req.run_id}/{out_folder}"
    state.undo_dir = str(out_path / "_undo")

    pk_map = _pk_map(ds_cfg)
    recognitions = recognize_dataset(tables, ds_cfg)
    suggest_category_variants(tables, recognitions, state)
    apply_auto_review_maps(tables, state, lineage, pk_map)
    apply_sentinel_nulls(tables, recognitions, rules, lineage, state, pk_map)
    apply_standardise_recognized(tables, recognitions, rules, lineage, state)
    apply_category_maps(tables, rules, lineage, state, pk_map)
    apply_rules(tables, rules, lineage, state, pk_map)
    apply_imputation(tables, rules, lineage, state, pk_map, column_roles, original_dtypes)
    apply_outliers(tables, rules, lineage, state, column_roles)

    protected = {(t, pk_map[t]) for t in pk_map if t in tables}
    llm_budget = [0]
    llm_calls = run_llm_advisory(tables, rules, profile_data, lineage, state, protected, llm_budget)
    warnings.extend(state.warnings)

    recon = []
    outputs = []
    outliers_flagged = 0
    cells_imputed = 0
    for t, df in tables.items():
        df = sanitize_string_nulls(df)
        for c in df.columns:
            if c.endswith("__outlier") or c.endswith("__imputed") or c.endswith("__high_null"):
                df[c] = df[c].astype(bool)
        tables[t] = df
        rel = f"{rel_base}/{t}.parquet"
        write_parquet(df, out_path / f"{t}.parquet")
        outputs.append(artifact_from_path(t, "parquet", rel, rows=len(df)))
        dropped = state.rows_dropped_by_table.get(t, 0)
        recon.append(reconcile_table(t, rows_in[t], len(df), dropped))
        for c in df.columns:
            if c.endswith("__outlier"):
                outliers_flagged += int(df[c].sum())
            if c.endswith("__imputed"):
                cells_imputed += int(df[c].sum())

    try:
        assert_reconciliation(recon)
    except ReconciliationError as e:
        return {
            "status": "error",
            "error": {"code": "INTERNAL", "message": str(e)},
            "metrics": {"silent_deletions": sum(r["silent_deletions"] for r in recon), "reconciliation": recon},
            "lineage_events": lineage.events,
            "llm_calls": llm_calls,
            "warnings": warnings,
        }

    rec_report = build_recognition_report(recognitions)
    write_json(rec_report, out_path / "recognition_report.json")
    write_json(state.quality_log, out_path / "quality_log.json")
    write_json(state.review_queue, out_path / "review_queue.json")
    write_json(state.dropped_rows, out_path / "dropped_rows.json")
    outputs.extend(
        [
            artifact_from_path("recognition_report", "json", f"{rel_base}/recognition_report.json"),
            artifact_from_path("quality_log", "json", f"{rel_base}/quality_log.json"),
            artifact_from_path("review_queue", "json", f"{rel_base}/review_queue.json"),
            artifact_from_path("dropped_rows", "json", f"{rel_base}/dropped_rows.json"),
        ]
    )

    status = "ok"
    if any("LLM" in w for w in warnings) and rules.get("llm_advisory", {}).get("enabled", True):
        status = "partial"
    if state.review_queue and status == "ok":
        status = "partial"

    if time.perf_counter() - t0 > TIMEOUT_CLEAN_S:
        warnings.append("clean approached timeout budget")
        status = "partial"

    metrics = {
        "rows_dropped": sum(state.rows_dropped_by_table.values()),
        "cells_imputed": cells_imputed,
        "outliers_flagged": outliers_flagged,
        "needs_review": len(state.review_queue),
        "silent_deletions": sum(r["silent_deletions"] for r in recon),
        "reconciliation_pass": all(r["ok"] for r in recon),
        "tables": recon,
    }
    return {
        "status": status,
        "outputs": outputs,
        "metrics": metrics,
        "warnings": warnings,
        "lineage_events": lineage.events,
        "llm_calls": llm_calls,
    }
