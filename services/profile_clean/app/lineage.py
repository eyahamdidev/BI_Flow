"""Build lineage events (returned in response; gateway writes events.jsonl)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .config import AGENT


class LineageTracker:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[dict[str, Any]] = []

    def emit(
        self,
        step: str,
        *,
        rule: str | None = None,
        rows_affected: int | None = None,
        method: str = "deterministic",
        params: dict[str, Any] | None = None,
        inputs: list[dict[str, Any]] | None = None,
        outputs: list[dict[str, Any]] | None = None,
        llm: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ev = {
            "event_id": str(uuid.uuid4()),
            "run_id": self.run_id,
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "agent": AGENT,
            "step": step,
            "inputs": inputs or [],
            "outputs": outputs or [],
            "rule": rule,
            "rows_affected": rows_affected,
            "method": method,
            "params": params or {},
            "llm": llm,
        }
        self.events.append(ev)
        return ev
