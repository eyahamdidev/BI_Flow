"""Paths relative to DATA_DIR. The auditor reads logs and JSON artifacts and never writes events.jsonl."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

RAW_SUFFIXES = {".parquet", ".csv", ".tsv", ".duckdb", ".xlsx", ".xls"}


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")).resolve()


def run_dir(run_id: str) -> Path:
    return data_dir() / "runs" / run_id


def rel_to_data(path: Path) -> str:
    return path.resolve().relative_to(data_dir()).as_posix()


def is_raw_table(path: Path) -> bool:
    return path.suffix.lower() in RAW_SUFFIXES


def read_text(path: Path) -> str | None:
    if not path.is_file() or is_raw_table(path):
        return None
    return path.read_text(encoding="utf-8")


def read_json(path: Path | None) -> Any | None:
    if path is None:
        return None
    text = read_text(path)
    if text is None or not text.strip():
        return None
    return json.loads(text)


def write_text(path: Path, text: str) -> None:
    if path.name == "events.jsonl":
        raise RuntimeError("auditor must not write events.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def find_input(inputs: dict[str, str], *names: str) -> Path | None:
    """Resolve an input by artifact key or file name. Raw tables are ignored."""
    wanted = {n.lower() for n in names}
    for key, rel in inputs.items():
        path = Path(rel)
        tokens = {key.split(".")[-1].lower(), path.name.lower(), path.stem.lower()}
        if tokens & wanted:
            candidate = path if path.is_absolute() else data_dir() / rel
            if not is_raw_table(candidate):
                return candidate
    return None


def events_path(run_id: str, inputs: dict[str, str], options: dict[str, Any]) -> Path:
    override = options.get("events_path")
    if override:
        raw = Path(str(override))
        return raw if raw.is_absolute() else data_dir() / str(override)
    found = find_input(inputs, "events", "events.jsonl")
    if found is not None:
        return found
    return run_dir(run_id) / "lineage" / "events.jsonl"


def load_events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file():
        return [], ["no lineage events logged for this run"]
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"skipped unreadable lineage line {lineno}")
            continue
        if isinstance(item, dict):
            events.append(item)
        else:
            warnings.append(f"skipped non-object lineage line {lineno}")
    return events, warnings


def artifact(name: str, kind: str, path: Path, label: str | None = None) -> dict[str, Any]:
    return {"name": name, "kind": kind, "path": rel_to_data(path), "rows": None, "sha256": None, "label": label}
