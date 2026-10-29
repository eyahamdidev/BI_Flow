"""Paths and dataset config for the ETL module. No dataset-specific code lives here."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

STAGE_FOLDER = "03_etl"
WAREHOUSE_NAME = "biflow.duckdb"
DBT_TEMPLATE = Path(__file__).resolve().parent.parent / "dbt_project"


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def repo_root() -> Path:
    """Folder that contains configs/ (repo root locally, /srv in the container)."""
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "configs" / "datasets").is_dir():
            return p
    return Path.cwd().resolve()


def load_dataset_yaml(config_ref: str | None, dataset: str) -> dict[str, Any]:
    path = Path(config_ref) if config_ref else Path("configs/datasets") / f"{dataset}.yaml"
    if not path.is_absolute():
        path = repo_root() / path
    if not path.exists():
        raise FileNotFoundError(f"dataset config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def resolve(rel: str) -> Path:
    """A path from the dataset YAML (relative to the repo root)."""
    p = Path(rel)
    return p if p.is_absolute() else repo_root() / p
