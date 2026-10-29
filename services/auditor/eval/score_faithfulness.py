"""Compute faithfulness after the supported column has been filled in by hand.

Reads eval/faithfulness_template.csv. Does not guess empty cells.
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    path = HERE / "faithfulness_template.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    labelled = []
    blank = 0
    for row in rows:
        raw = (row.get("supported (1/0)") or "").strip()
        if raw in {"1", "0"}:
            labelled.append(int(raw))
        else:
            blank += 1
    if not labelled or blank:
        print(f"not labelled yet: {len(labelled)} filled, {blank} empty")
        return
    rate = sum(labelled) / len(labelled)
    print(f"claims {len(labelled)}")
    print(f"faithfulness {rate:.4f}")


if __name__ == "__main__":
    main()
