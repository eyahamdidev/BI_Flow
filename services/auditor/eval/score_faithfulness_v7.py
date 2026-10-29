"""Score hand labels in eval/faithfulness_v7.csv. Empty cells are not guessed.

Explain cases and synthetic sheets are scored separately. Each rate includes n
and a 95% Wilson interval. The explain set is n=20 before any labels exist.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent


def _bit(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if text in {"1", "0"}:
        return int(text)
    return None


def _report(name: str, labelled: list[int], blank: int, kind: str) -> None:
    from app.wilson import wilson_interval

    print(f"{name} {kind}: filled {len(labelled)}, empty {blank}, n_rows {len(labelled) + blank}")
    if not labelled or blank:
        print(f"{name} {kind}: not labelled yet")
        return
    rate = sum(labelled) / len(labelled)
    low, high = wilson_interval(sum(labelled), len(labelled))
    print(f"{name} {kind}: rate {rate:.4f} n {len(labelled)} wilson95 [{low:.4f}, {high:.4f}]")


def main() -> None:
    path = HERE / "faithfulness_v7.csv"
    if not path.is_file():
        print("faithfulness_v7.csv is not written yet")
        return
    groups: dict[str, dict[str, list]] = {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        case = (row.get("case") or "").strip()
        if not case or case.startswith("#"):
            continue
        section = (row.get("section") or "").strip() or ("synthetic" if case.startswith("syn") else "explain")
        bucket = groups.setdefault(section, {"supported": [], "supported_blank": 0, "omission": [], "omission_blank": 0})
        frame = (row.get("frame") or "").strip()
        if frame == "(omission)":
            bit = _bit(row.get("misleading_by_omission (1/0)"))
            if bit is None:
                bucket["omission_blank"] += 1
            else:
                bucket["omission"].append(bit)
            continue
        bit = _bit(row.get("supported (1/0)"))
        if bit is None:
            bucket["supported_blank"] += 1
        else:
            bucket["supported"].append(bit)
    if not groups:
        print("not labelled yet: no data rows")
        return
    for name in ("explain", "synthetic"):
        bucket = groups.get(name)
        if bucket is None:
            continue
        _report(name, bucket["supported"], bucket["supported_blank"], "supported")
        _report(name, bucket["omission"], bucket["omission_blank"], "omission")
    print("warning: the explain set has n=20 cases. That interval is wide. These sheets do not support a tight rate.")
    print("warning: synthetic rows cover shapes. Do not quote a rate from them as a sample-size result.")


if __name__ == "__main__":
    main()
