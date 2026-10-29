"""Row reconciliation: rows_in - rows_dropped == rows_out."""
from __future__ import annotations

from typing import Any

from .errors import ReconciliationError


def reconcile_table(
    table: str,
    rows_in: int,
    rows_out: int,
    rows_dropped_logged: int,
) -> dict[str, Any]:
    silent = rows_in - rows_dropped_logged - rows_out
    ok = silent == 0 and rows_in - rows_dropped_logged == rows_out
    return {
        "table": table,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_dropped_logged": rows_dropped_logged,
        "silent_deletions": silent,
        "ok": ok,
    }


def assert_reconciliation(results: list[dict[str, Any]]) -> None:
    bad = [r for r in results if not r["ok"]]
    if bad:
        msg = "; ".join(f"{r['table']}: silent={r['silent_deletions']}" for r in bad)
        raise ReconciliationError(f"row reconciliation failed: {msg}")
