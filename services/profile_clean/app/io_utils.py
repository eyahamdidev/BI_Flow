"""Safe paths, hashing, parquet I/O."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import data_dir
from .errors import BadInputError


def validate_input_path(rel: str, name: str = "input") -> Path:
    if not rel or rel.startswith("/") or "\\" in rel:
        raise BadInputError(f"{name}: path must be relative to DATA_DIR")
    if ".." in Path(rel).parts:
        raise BadInputError(f"{name}: path traversal not allowed")
    full = (data_dir() / rel).resolve()
    root = data_dir().resolve()
    if not str(full).startswith(str(root)):
        raise BadInputError(f"{name}: path escapes DATA_DIR")
    return full


def run_dir(run_id: str, stage_folder: str) -> Path:
    if ".." in run_id or "/" in run_id or "\\" in run_id:
        raise BadInputError("invalid run_id")
    d = data_dir() / "runs" / run_id / stage_folder
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def artifact_from_path(name: str, kind: str, rel_path: str, rows: int | None = None, label: str | None = None) -> dict[str, Any]:
    full = data_dir() / rel_path
    sh = sha256_file(full) if full.exists() else None
    return {"name": name, "kind": kind, "path": rel_path, "rows": rows, "sha256": sh, "label": label}
