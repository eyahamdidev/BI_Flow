"""Published explanations, keyed so the same question returns the same text.

The key is the hash of the KPI, the period, the comparison, the fact sheet,
the prompt version, the model, and the language. A later run with that same
key does not call the model again. Language is part of the key because the
same sheet can be rendered in English and in French.
"""

from __future__ import annotations

# Bump when the code that ranks drivers / fills frames changes: a published answer is only reused if it was produced
# by the same logic (v2: contributions ranked in the direction of the change, absolute delta after the direction word).
EXPLAIN_LOGIC_VERSION = 3  # v3: the checker accepts the size of a negative change

import hashlib
import json
from typing import Any

from .io_utils import data_dir


def explanation_key(
    kpi_id: str,
    period: str,
    compare_to: str | None,
    fact_sheet: dict[str, Any],
    prompt_version: str,
    model: str,
    lang: str = "en",
) -> str:
    blob = json.dumps(
        {
            "kpi_id": str(kpi_id),
            "period": str(period),
            "compare_to": None if compare_to in (None, "") else str(compare_to),
            "fact_sheet": fact_sheet,
            "prompt_version": prompt_version,
            "model": model,
            "lang": lang or "en",
            "logic_version": EXPLAIN_LOGIC_VERSION,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def response_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def _path(key: str):
    return data_dir() / "auditor" / "explanations" / f"{key}.json"


def load_explanation(key: str) -> dict[str, Any] | None:
    path = _path(key)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("key") != key or not isinstance(payload.get("text"), str):
        return None
    return payload


def save_explanation(record: dict[str, Any]) -> None:
    path = _path(str(record["key"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
