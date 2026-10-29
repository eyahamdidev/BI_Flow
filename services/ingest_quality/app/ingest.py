from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from biflow_contracts import Artifact, LineageEvent, RunRequest, RunResponse

from .connectors import get_connector


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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def execute_ingest(req: RunRequest) -> RunResponse:
    repo_root = _get_repo_root()
    data_dir = _get_data_dir()

    # Locate dataset configuration YAML
    config_ref = req.config_ref or f"configs/datasets/{req.dataset}.yaml"
    config_path = Path(config_ref)
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Dataset config not found at: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        ds_cfg: dict[str, Any] = yaml.safe_load(f)

    source_cfg = ds_cfg.get("source")
    if not source_cfg:
        raise ValueError(f"Dataset config missing 'source' section in {config_path}")

    # Load tables using appropriate connector
    # Columns declared `str` in expected_schema are read as text: otherwise pandas turns zip "01037" into 1037
    # and validation (which expects str) fails. Everything else keeps pandas' type inference.
    text_columns = {
        table: [c for c, spec in (cols or {}).items() if (spec.get("type") if isinstance(spec, dict) else spec) == "str"]
        for table, cols in (ds_cfg.get("expected_schema") or {}).items()
    }
    connector = get_connector({**source_cfg, "text_columns": text_columns}, root_dir=repo_root)
    dfs = connector.load()

    # Destination folder under data/runs/<run_id>/00_ingest/
    out_dir = data_dir / "runs" / req.run_id / "00_ingest"
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Artifact] = []
    manifest_tables: dict[str, Any] = {}
    total_rows = 0

    for table_name, df in dfs.items():
        parquet_file = out_dir / f"{table_name}.parquet"
        df.to_parquet(parquet_file, index=False)
        file_hash = _sha256(parquet_file)
        row_count = len(df)
        total_rows += row_count

        rel_path = f"runs/{req.run_id}/00_ingest/{table_name}.parquet"
        outputs.append(
            Artifact(
                name=table_name,
                kind="parquet",
                path=rel_path,
                rows=row_count,
                sha256=file_hash,
            )
        )
        manifest_tables[table_name] = {
            "rows": row_count,
            "sha256": file_hash,
            "path": rel_path,
        }

    # Write manifest.json
    manifest_data = {
        "source": source_cfg,
        "timestamp": _now(),
        "run_id": req.run_id,
        "dataset": req.dataset,
        "tables": manifest_tables,
        "rows_total": total_rows,
    }
    manifest_file = out_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    manifest_hash = _sha256(manifest_file)
    manifest_rel_path = f"runs/{req.run_id}/00_ingest/manifest.json"

    # Prepend manifest artifact to outputs
    outputs.insert(
        0,
        Artifact(
            name="manifest",
            kind="json",
            path=manifest_rel_path,
            rows=None,
            sha256=manifest_hash,
        ),
    )

    source_type = source_cfg.get("type", "unknown").lower()
    step_name = f"ingest_{source_type}" if source_type in ("csv", "sql", "api") else "ingest_csv"

    # Build lineage event
    lineage = LineageEvent(
        event_id=f"ingest-{req.run_id}-{uuid.uuid4().hex[:6]}",
        run_id=req.run_id,
        ts=_now(),
        agent="ingest_quality",
        step=step_name,
        inputs=[],
        outputs=[
            {"name": a.name, "path": a.path, "rows": a.rows, "sha256": a.sha256}
            for a in outputs
            if a.kind == "parquet"
        ],
        rule=f"{connector.__class__.__name__}({req.dataset})",
        rows_affected=total_rows,
        method="deterministic",
        params={"source_type": source_type},
    )

    return RunResponse(
        request_id=req.request_id,
        run_id=req.run_id,
        module="ingest_quality",
        status="ok",
        outputs=outputs,
        metrics={"tables": len(dfs), "rows_total": total_rows},
        lineage_events=[lineage],
    )

