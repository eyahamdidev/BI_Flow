"""Shared helpers for the semantic_kpi module (paths, config, lineage). No dataset-specific code."""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "configs" / "datasets").is_dir():
            return p
    return Path.cwd().resolve()


def load_dataset(config_ref: str | None, dataset: str) -> dict[str, Any]:
    path = Path(config_ref) if config_ref else Path("configs/datasets") / f"{dataset}.yaml"
    path = path if path.is_absolute() else repo_root() / path
    if not path.exists():
        raise FileNotFoundError(f"dataset config not found: {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if parent := cfg.pop("extends", None):  # standalone use; the gateway normally passes a resolved config
        base = load_dataset(str(path.parent / parent), dataset)
        base.update({k: v for k, v in cfg.items() if not isinstance(v, dict)})
        for k, v in cfg.items():
            if isinstance(v, dict):
                base[k] = {**base.get(k, {}), **v}
        cfg = base
    return cfg


def load_catalog(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    ref = cfg.get("kpi_file") or f"configs/kpis/{cfg.get('domain', 'default')}.yaml"
    p = Path(ref)
    p = p if p.is_absolute() else repo_root() / p
    return yaml.safe_load(p.read_text(encoding="utf-8")) or []


def stage_dir(run_id: str, folder: str) -> tuple[Path, str]:
    rel = f"runs/{run_id}/{folder}"
    d = data_dir() / rel
    d.mkdir(parents=True, exist_ok=True)
    return d, rel


def find_input(inputs: dict[str, str], name: str) -> Path | None:
    """Input artifact by name, e.g. 'warehouse' matches key 'etl.warehouse'."""
    for key, rel in inputs.items():
        if key.split(".")[-1] == name:
            return data_dir() / rel
    return None


def event(run_id: str, step: str, **kw: Any) -> dict[str, Any]:
    return {"event_id": str(uuid.uuid4()), "run_id": run_id, "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "agent": "semantic_kpi", "step": step, "method": "deterministic", **kw}


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
