"""Persist user-approved decisions per dataset slug (YAML, not ML)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import data_dir


def decisions_path(slug: str) -> Path:
    return data_dir() / "decisions" / f"{slug}.yaml"


def load_decisions_file(slug: str) -> dict[str, Any]:
    p = decisions_path(slug)
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def save_decisions_file(slug: str, decisions: dict[str, Any]) -> Path:
    p = decisions_path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(decisions, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


def merge_decisions(cfg: dict[str, Any], slug: str) -> dict[str, Any]:
    file_dec = load_decisions_file(slug)
    merged = dict(cfg.get("decisions", {}))
    for k, v in file_dec.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    cfg = dict(cfg)
    cfg["decisions"] = merged
    if merged.get("category_maps"):
        rules = dict(cfg.get("cleaning_rules", {}))
        rules["category_maps"] = {**rules.get("category_maps", {}), **merged["category_maps"]}
        cfg["cleaning_rules"] = rules
    if merged.get("na_tokens"):
        rules = dict(cfg.get("cleaning_rules", {}))
        rules["na_tokens"] = list(set(rules.get("na_tokens", [])) | set(merged["na_tokens"]))
        cfg["cleaning_rules"] = rules
    return cfg
