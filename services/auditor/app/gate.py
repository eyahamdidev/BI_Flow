"""Gate arithmetic for the paced v7 runs. Transport fallbacks can be reported separately."""

from __future__ import annotations


def case_rates(rows: list[dict], drop_transport: bool = False) -> dict:
    kept = []
    for row in rows:
        transport = row.get("source") == "fallback" and row.get("fallback_cause") in {"http_429", "timeout"}
        if drop_transport and transport:
            continue
        kept.append(row)
    n = len(kept)
    first = sum(1 for row in kept if row.get("source") == "llm" and row.get("first_try_pass") is True)
    fallback = sum(1 for row in kept if row.get("source") == "fallback")
    return {
        "n": n,
        "dropped": len(rows) - n,
        "first_try_pass_rate": round(first / n, 4) if n else None,
        "fallback_rate": round(fallback / n, 4) if n else None,
    }


def gate_passes(runs: list[list[dict]], drop_transport: bool = False, expect_n: int = 20) -> bool:
    if len(runs) < 3:
        return False
    for rows in runs:
        stats = case_rates(rows, drop_transport=drop_transport)
        if not drop_transport and stats["n"] != expect_n:
            return False
        if stats["n"] == 0:
            return False
        if stats["first_try_pass_rate"] != 1.0 or stats["fallback_rate"] != 0.0:
            return False
    return True


def identical_frame_sets(runs: list[list[dict]]) -> int:
    """Cases whose chosen frame set is the same on every run. Order does not count."""
    if not runs:
        return 0
    ids = [row.get("id") for row in runs[0]]
    count = 0
    for case_id in ids:
        sets = []
        for run in runs:
            match = next((row for row in run if row.get("id") == case_id), None)
            if match is None:
                sets.append(None)
                continue
            sets.append(frozenset(match.get("frames") or []))
        if sets and all(item == sets[0] for item in sets):
            count += 1
    return count
