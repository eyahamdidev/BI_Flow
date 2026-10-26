"""Runtime configuration for profile_clean (no dataset-specific logic)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

TIMEOUT_PROFILE_S = 60
TIMEOUT_CLEAN_S = 120
TIMEOUT_EVAL_S = 120

MODULE = "profile_clean"
AGENT = "profile_clean"
MAX_LLM_CALLS_PER_RUN = 10
RANDOM_STATE = 42


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "configs" / "datasets").is_dir():
            return p
    return Path.cwd().resolve()


def config_dir() -> Path:
    d = os.getenv("BIFLOW_CONFIG_DIR")
    if d:
        return Path(d).resolve()
    return repo_root() / "config"


def load_dataset_yaml(config_ref: str | None, dataset: str) -> dict[str, Any]:
    root = repo_root()
    if config_ref:
        path = Path(config_ref)
        if not path.is_absolute():
            path = root / path
    else:
        path = root / "configs" / "datasets" / f"{dataset}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"dataset config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def stage_output_dir(run_id: str, mode: str, options: dict[str, Any]) -> str:
    if mode == "profile":
        stage = options.get("stage", "before")
        if stage == "after":
            return options.get("output_stage", "03_profile_after")
        return options.get("output_stage", "01_profile")
    if mode == "clean":
        return options.get("output_stage", "02_clean")
    return options.get("output_stage", "01_profile")
