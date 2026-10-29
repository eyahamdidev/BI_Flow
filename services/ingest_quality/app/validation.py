from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa
import yaml
from biflow_contracts import Artifact, ErrorInfo, LineageEvent, RunRequest, RunResponse


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


def _map_pandera_type(type_name: str) -> pa.DataType | type:
    tn = type_name.lower().strip()
    if tn in ("str", "string", "text", "object"):
        return pa.String
    elif tn in ("int", "integer", "int64", "int32"):
        return pa.Int64
    elif tn in ("float", "float64", "double", "numeric", "number"):
        return pa.Float64
    elif tn in ("datetime", "timestamp", "date"):
        return pa.DateTime
    elif tn in ("bool", "boolean"):
        return pa.Bool
    return pa.String


def build_pandera_schema(table_schema_cfg: dict[str, Any], coerce: bool = False) -> pa.DataFrameSchema:
    """Builds a Pandera DataFrameSchema from the dataset YAML expected_schema definition.

    coerce=False (cleaned data, output contract): the column must ALREADY have the declared type.
    coerce=True  (raw ingest, input contract): the column must be CONVERTIBLE to the declared type. A raw CSV holds
    dates as text; the cleaner parses them. Values that cannot be converted are still reported as errors."""
    columns: dict[str, pa.Column] = {}

    for col_name, spec in table_schema_cfg.items():
        if isinstance(spec, dict):
            raw_type = spec.get("type", "str")
            nullable = spec.get("nullable", False)
            required = spec.get("required", True)
        else:
            raw_type = str(spec)
            nullable = False
            required = True

        pa_dtype = _map_pandera_type(raw_type)
        columns[col_name] = pa.Column(
            pa_dtype,
            nullable=nullable,
            required=required,
            coerce=coerce,
        )

    return pa.DataFrameSchema(columns=columns, strict=False, coerce=coerce)


def _load_table_dataframes(req: RunRequest, expected_tables: list[str]) -> tuple[dict[str, pd.DataFrame], str]:
    data_dir = _get_data_dir()
    dfs: dict[str, pd.DataFrame] = {}
    stage_used = "00_ingest"

    stage_pref = req.options.get("stage")
    stages_to_check = [stage_pref] if stage_pref else ["clean", "00_ingest"]

    for table_name in expected_tables:
        found_path: Path | None = None
        for pref in stages_to_check:
            if not pref:
                continue
            key = f"{pref}.{table_name}"
            if key in req.inputs:
                p = (data_dir / req.inputs[key]).resolve()
                if p.exists():
                    found_path = p
                    stage_used = pref
                    break

        if not found_path:
            for s in stages_to_check:
                if not s:
                    continue
                cand = data_dir / "runs" / req.run_id / s / f"{table_name}.parquet"
                if cand.exists():
                    found_path = cand
                    stage_used = s
                    break

        if found_path and found_path.exists():
            dfs[table_name] = pd.read_parquet(found_path)

    return dfs, stage_used


def execute_validate(req: RunRequest) -> RunResponse:
    repo_root = _get_repo_root()
    data_dir = _get_data_dir()

    config_ref = req.config_ref or f"configs/datasets/{req.dataset}.yaml"
    config_path = Path(config_ref)
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    if not config_path.exists():
        return RunResponse(
            request_id=req.request_id,
            run_id=req.run_id,
            module="ingest_quality",
            status="error",
            error=ErrorInfo(code="BAD_INPUT", message=f"Config file not found: {config_ref}"),
        )

    with config_path.open("r", encoding="utf-8") as f:
        ds_cfg: dict[str, Any] = yaml.safe_load(f)

    expected_schema = ds_cfg.get("expected_schema", {})
    if not expected_schema:
        return RunResponse(
            request_id=req.request_id,
            run_id=req.run_id,
            module="ingest_quality",
            status="error",
            error=ErrorInfo(code="BAD_INPUT", message="expected_schema missing in dataset config"),
        )

    dfs, stage_used = _load_table_dataframes(req, list(expected_schema.keys()))

    if not dfs:
        return RunResponse(
            request_id=req.request_id,
            run_id=req.run_id,
            module="ingest_quality",
            status="error",
            error=ErrorInfo(
                code="BAD_INPUT",
                message=f"No input tables found to validate for run_id '{req.run_id}'",
            ),
        )

    errors: list[dict[str, Any]] = []
    tables_checked = 0

    for table_name, col_specs in expected_schema.items():
        if table_name not in dfs:
            continue

        tables_checked += 1
        df = dfs[table_name]
        # raw ingest output = input contract (convertible); anything else (clean) = output contract (strict)
        schema = build_pandera_schema(col_specs, coerce=stage_used in ("ingest", "00_ingest", "raw"))

        # Pre-check columns present and nullability
        for col_name, col_spec in col_specs.items():
            nullable = col_spec.get("nullable", False) if isinstance(col_spec, dict) else False
            expected_type = col_spec.get("type", str(col_spec)) if isinstance(col_spec, dict) else str(col_spec)

            if col_name not in df.columns:
                errors.append({
                    "table": table_name,
                    "column": col_name,
                    "expected": f"Column present ({expected_type})",
                    "found": "Column missing",
                })
                continue

            if not nullable and df[col_name].isnull().any():
                null_count = int(df[col_name].isnull().sum())
                errors.append({
                    "table": table_name,
                    "column": col_name,
                    "expected": "nullable=False",
                    "found": f"{null_count} null value(s) found",
                })

        # Pandera schema-level validation
        try:
            schema.validate(df, lazy=True)
        except pa.errors.SchemaErrors as err:
            if hasattr(err, "failure_cases") and err.failure_cases is not None:
                for _, row in err.failure_cases.iterrows():
                    col = str(row.get("column", "unknown"))
                    check = str(row.get("check", "schema_check"))
                    reason = str(row.get("failure_case", ""))
                    # Avoid duplicate reporting if already detected in pre-check
                    if not any(e["table"] == table_name and e["column"] == col for e in errors):
                        errors.append({
                            "table": table_name,
                            "column": col,
                            "expected": check,
                            "found": reason or "type/value mismatch",
                        })
            else:
                for failure in getattr(err, "schema_errors", []):
                    col = getattr(failure, "schema", None) and getattr(failure.schema, "name", "unknown") or "unknown"
                    if not any(e["table"] == table_name and e["column"] == str(col) for e in errors):
                        errors.append({
                            "table": table_name,
                            "column": str(col),
                            "expected": str(getattr(failure, "check", "valid schema")),
                            "found": str(failure),
                        })
        except Exception as err:
            errors.append({
                "table": table_name,
                "column": "all",
                "expected": "valid schema",
                "found": str(err),
            })

    out_dir = data_dir / "runs" / req.run_id / "00_ingest"
    out_dir.mkdir(parents=True, exist_ok=True)
    # one file per stage: validate_raw and validate (clean) must not overwrite each other
    stage_tag = "".join(ch for ch in str(req.options.get("stage") or stage_used) if ch.isalnum() or ch == "_")
    report_file = out_dir / f"validation_report_{stage_tag}.json"

    report_data = {
        "timestamp": _now(),
        "run_id": req.run_id,
        "dataset": req.dataset,
        "stage_inspected": stage_used,
        "tables_checked": tables_checked,
        "schema_errors_count": len(errors),
        "errors": errors,
        "status": "failed" if errors else "passed",
    }
    report_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    report_hash = _sha256(report_file)
    report_rel_path = f"runs/{req.run_id}/00_ingest/validation_report_{stage_tag}.json"

    outputs = [
        Artifact(
            name="validation_report",
            kind="json",
            path=report_rel_path,
            rows=None,
            sha256=report_hash,
        )
    ]

    lineage = LineageEvent(
        event_id=f"validate-{req.run_id}-{uuid.uuid4().hex[:6]}",
        run_id=req.run_id,
        ts=_now(),
        agent="ingest_quality",
        step="validate_schema",
        inputs=[{"name": t, "rows": len(df)} for t, df in dfs.items()],
        outputs=[{"name": "validation_report", "path": report_rel_path, "sha256": report_hash}],
        rule="pandera(expected_schema)",
        rows_affected=None,
        method="deterministic",
        params={"tables_checked": tables_checked, "errors_count": len(errors)},
    )

    if errors:
        err_lines = [
            f"- Table '{e['table']}', Column '{e['column']}': expected [{e['expected']}], found [{e['found']}]"
            for e in errors[:10]
        ]
        if len(errors) > 10:
            err_lines.append(f"... and {len(errors) - 10} more schema violations")
        error_msg = f"SCHEMA_MISMATCH in {len(errors)} check(s):\n" + "\n".join(err_lines)

        return RunResponse(
            request_id=req.request_id,
            run_id=req.run_id,
            module="ingest_quality",
            status="error",
            outputs=outputs,
            metrics={"schema_errors": len(errors), "tables_checked": tables_checked},
            lineage_events=[lineage],
            error=ErrorInfo(code="SCHEMA_MISMATCH", message=error_msg),
        )

    return RunResponse(
        request_id=req.request_id,
        run_id=req.run_id,
        module="ingest_quality",
        status="ok",
        outputs=outputs,
        metrics={"schema_errors": 0, "tables_checked": tables_checked},
        lineage_events=[lineage],
    )
