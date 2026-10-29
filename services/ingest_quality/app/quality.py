from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from biflow_contracts import Artifact, LineageEvent, RunRequest, RunResponse


def _get_repo_root() -> Path:
    # Search upward for the folder holding configs/datasets: the repo root locally, /srv in the container.
    # (A fixed parents[3] pointed at "/" inside the container, where the code lives in /srv/service/app.)
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "configs" / "datasets").is_dir():
            return p
    return Path.cwd().resolve()


def _get_data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", _get_repo_root() / "data")).resolve()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_table_completeness(df: pd.DataFrame) -> float:
    total_cells = df.size
    if total_cells == 0:
        return 100.0
    null_cells = int(df.isnull().sum().sum())
    return max(0.0, min(100.0, 100.0 * (1.0 - (null_cells / total_cells))))


def compute_table_uniqueness(df: pd.DataFrame) -> float:
    total_rows = len(df)
    if total_rows <= 1:
        return 100.0

    dup_rows = int(df.duplicated().sum())
    row_uniqueness = 1.0 - (dup_rows / total_rows)

    # Check primary key column if identifiable
    id_cols = [c for c in df.columns if c.endswith("_id") or c == "id"]
    if id_cols:
        pk = id_cols[0]
        pk_uniqueness = df[pk].nunique() / total_rows
        combined = (row_uniqueness * 0.5) + (pk_uniqueness * 0.5)
    else:
        combined = row_uniqueness

    return max(0.0, min(100.0, 100.0 * combined))


def compute_table_validity(df: pd.DataFrame, expected_schema: dict[str, Any] | None = None) -> float:
    if len(df) == 0:
        return 100.0

    valid_checks = 0
    total_checks = 0

    # 1. Negative numeric checks on price, value, freight, weight, etc.
    for col in df.columns:
        col_lower = col.lower()
        if pd.api.types.is_numeric_dtype(df[col]):
            if any(term in col_lower for term in ("price", "value", "freight", "weight", "cost", "score")):
                non_nulls = df[col].dropna()
                if len(non_nulls) > 0:
                    total_checks += len(non_nulls)
                    valid_checks += int((non_nulls >= 0).sum())

    # 2. Schema type compatibility checks if available
    if expected_schema:
        for col, spec in expected_schema.items():
            if col in df.columns:
                target_type = spec.get("type", str(spec)) if isinstance(spec, dict) else str(spec)
                target_type = target_type.lower()
                non_nulls = df[col].dropna()
                if len(non_nulls) > 0:
                    total_checks += len(non_nulls)
                    if target_type in ("int", "integer"):
                        valid_checks += int(pd.to_numeric(non_nulls, errors="coerce").notnull().sum())
                    elif target_type in ("float", "double", "numeric"):
                        valid_checks += int(pd.to_numeric(non_nulls, errors="coerce").notnull().sum())
                    elif target_type in ("datetime", "timestamp", "date"):
                        valid_checks += int(pd.to_datetime(non_nulls, errors="coerce").notnull().sum())
                    else:
                        valid_checks += len(non_nulls)

    if total_checks == 0:
        return 100.0

    return max(0.0, min(100.0, 100.0 * (valid_checks / total_checks)))


def compute_consistency(dfs: dict[str, pd.DataFrame], relationships: list[dict[str, str]]) -> tuple[float, dict[str, float]]:
    if not relationships or not dfs:
        return 100.0, {}

    rel_scores: dict[str, float] = {}
    valid_rates: list[float] = []

    for rel in relationships:
        from_spec = rel.get("from", "")
        to_spec = rel.get("to", "")
        if "." not in from_spec or "." not in to_spec:
            continue

        child_table, child_col = from_spec.split(".", 1)
        parent_table, parent_col = to_spec.split(".", 1)

        if child_table not in dfs or parent_table not in dfs:
            continue

        child_df = dfs[child_table]
        parent_df = dfs[parent_table]

        if child_col not in child_df.columns or parent_col not in parent_df.columns:
            continue

        child_keys = child_df[child_col].dropna()
        if len(child_keys) == 0:
            rel_scores[f"{from_spec}->{to_spec}"] = 100.0
            valid_rates.append(1.0)
            continue

        parent_keys_set = set(parent_df[parent_col].dropna().unique())
        matched = child_keys.isin(parent_keys_set).sum()
        rate = float(matched) / len(child_keys)

        rel_scores[f"{from_spec}->{to_spec}"] = round(rate * 100.0, 1)
        valid_rates.append(rate)

    if not valid_rates:
        return 100.0, {}

    avg_consistency = 100.0 * (sum(valid_rates) / len(valid_rates))
    return max(0.0, min(100.0, avg_consistency)), rel_scores


def compute_timeliness(dfs: dict[str, pd.DataFrame]) -> float:
    # Check date ordering in orders table if present
    orders_df = dfs.get("orders")
    if orders_df is None or len(orders_df) == 0:
        return 100.0

    checks = 0
    passed = 0

    purchase_col = "order_purchase_timestamp"
    delivered_col = "order_delivered_customer_date"
    estimated_col = "order_estimated_delivery_date"

    if purchase_col in orders_df.columns and delivered_col in orders_df.columns:
        p_dates = pd.to_datetime(orders_df[purchase_col], errors="coerce")
        d_dates = pd.to_datetime(orders_df[delivered_col], errors="coerce")
        valid_mask = p_dates.notnull() & d_dates.notnull()
        if valid_mask.any():
            checks += int(valid_mask.sum())
            passed += int((d_dates[valid_mask] >= p_dates[valid_mask]).sum())

    if purchase_col in orders_df.columns and estimated_col in orders_df.columns:
        p_dates = pd.to_datetime(orders_df[purchase_col], errors="coerce")
        e_dates = pd.to_datetime(orders_df[estimated_col], errors="coerce")
        valid_mask = p_dates.notnull() & e_dates.notnull()
        if valid_mask.any():
            checks += int(valid_mask.sum())
            passed += int((e_dates[valid_mask] >= p_dates[valid_mask]).sum())

    if checks == 0:
        return 100.0

    return max(0.0, min(100.0, 100.0 * (passed / checks)))


def _load_all_available_tables(req: RunRequest) -> tuple[dict[str, pd.DataFrame], str]:
    data_dir = _get_data_dir()
    dfs: dict[str, pd.DataFrame] = {}
    stage = req.options.get("stage", "before")

    # If stage == "after", look in clean stage first
    candidate_stages = ["clean", "00_ingest"] if stage == "after" else ["00_ingest", "clean"]
    resolved_stage = candidate_stages[0]

    # Look through req.inputs first
    for k, v in req.inputs.items():
        if k.endswith(".parquet") or not k.endswith(".json"):
            tbl_name = k.split(".")[-1]
            p = (data_dir / v).resolve()
            if p.exists() and p.suffix == ".parquet":
                dfs[tbl_name] = pd.read_parquet(p)

    if not dfs:
        # Check files in runs directory
        for s in candidate_stages:
            stage_dir = data_dir / "runs" / req.run_id / s
            if stage_dir.exists():
                for p in stage_dir.glob("*.parquet"):
                    dfs[p.stem] = pd.read_parquet(p)
                if dfs:
                    resolved_stage = s
                    break

    return dfs, resolved_stage


def execute_score(req: RunRequest) -> RunResponse:
    repo_root = _get_repo_root()
    data_dir = _get_data_dir()

    # Load dataset config
    config_ref = req.config_ref or f"configs/datasets/{req.dataset}.yaml"
    config_path = Path(config_ref)
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    weights = {"completeness": 0.30, "uniqueness": 0.20, "validity": 0.20, "consistency": 0.20, "timeliness": 0.10}
    relationships: list[dict[str, str]] = []
    expected_schema: dict[str, Any] = {}

    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            ds_cfg: dict[str, Any] = yaml.safe_load(f) or {}
            custom_weights = ds_cfg.get("quality_score", {}).get("weights")
            if custom_weights:
                weights.update(custom_weights)
            relationships = ds_cfg.get("relationships", [])
            expected_schema = ds_cfg.get("expected_schema", {})

    dfs, stage_used = _load_all_available_tables(req)

    # Calculate per-table and global dimensions
    table_scores: dict[str, dict[str, float]] = {}
    completeness_list: list[float] = []
    uniqueness_list: list[float] = []
    validity_list: list[float] = []

    for name, df in dfs.items():
        comp = compute_table_completeness(df)
        uniq = compute_table_uniqueness(df)
        val = compute_table_validity(df, expected_schema.get(name))

        completeness_list.append(comp)
        uniqueness_list.append(uniq)
        validity_list.append(val)

        table_scores[name] = {
            "completeness": round(comp, 1),
            "uniqueness": round(uniq, 1),
            "validity": round(val, 1),
            "rows": len(df),
        }

    dim_completeness = sum(completeness_list) / len(completeness_list) if completeness_list else 100.0
    dim_uniqueness = sum(uniqueness_list) / len(uniqueness_list) if uniqueness_list else 100.0
    dim_validity = sum(validity_list) / len(validity_list) if validity_list else 100.0
    dim_consistency, rel_breakdown = compute_consistency(dfs, relationships)
    dim_timeliness = compute_timeliness(dfs)

    overall = (
        weights["completeness"] * dim_completeness
        + weights["uniqueness"] * dim_uniqueness
        + weights["validity"] * dim_validity
        + weights["consistency"] * dim_consistency
        + weights["timeliness"] * dim_timeliness
    )

    metrics = {
        "overall": round(overall, 1),
        "completeness": round(dim_completeness, 1),
        "uniqueness": round(dim_uniqueness, 1),
        "validity": round(dim_validity, 1),
        "consistency": round(dim_consistency, 1),
        "timeliness": round(dim_timeliness, 1),
    }

    # Save artifact quality_score.json
    out_dir = data_dir / "runs" / req.run_id / "00_ingest"
    out_dir.mkdir(parents=True, exist_ok=True)
    # one file per stage: score_before and score_after must not overwrite each other (dashboard shows before/after)
    stage_tag = "".join(ch for ch in str(req.options.get("stage", "before")) if ch.isalnum() or ch == "_")
    score_file = out_dir / f"quality_score_{stage_tag}.json"

    score_artifact_data = {
        "timestamp": _now(),
        "run_id": req.run_id,
        "dataset": req.dataset,
        "stage": req.options.get("stage", "before"),
        "weights": weights,
        "metrics": metrics,
        "tables": table_scores,
        "relationships": rel_breakdown,
    }
    score_file.write_text(json.dumps(score_artifact_data, indent=2), encoding="utf-8")
    score_hash = _sha256(score_file)
    rel_path = f"runs/{req.run_id}/00_ingest/quality_score_{stage_tag}.json"

    outputs = [
        Artifact(
            name="quality_score",
            kind="json",
            path=rel_path,
            rows=None,
            sha256=score_hash,
        )
    ]

    lineage = LineageEvent(
        event_id=f"score-{req.run_id}-{uuid.uuid4().hex[:6]}",
        run_id=req.run_id,
        ts=_now(),
        agent="ingest_quality",
        step="score",
        inputs=[{"name": t, "rows": len(df)} for t, df in dfs.items()],
        outputs=[{"name": "quality_score", "path": rel_path, "sha256": score_hash}],
        rule="quality_score(weights.yaml)",
        rows_affected=None,
        method="deterministic",
        params={"stage": req.options.get("stage", "before"), "overall": metrics["overall"]},
    )

    return RunResponse(
        request_id=req.request_id,
        run_id=req.run_id,
        module="ingest_quality",
        status="ok",
        outputs=outputs,
        metrics=metrics,
        lineage_events=[lineage],
    )

