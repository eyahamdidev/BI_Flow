"""Mean clarity per source after eval/readability.json form_scores is filled in."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    scores = json.loads((HERE / "readability.json").read_text(encoding="utf-8")).get("form_scores") or []
    key = json.loads((HERE / "readability_key.json").read_text(encoding="utf-8"))
    source_of = {item["item"]: item["source"] for item in key.get("items") or []}
    buckets: dict[str, list[float]] = {"template": [], "model": []}
    for row in scores:
        source = source_of.get(row.get("item"))
        clarity = row.get("clarity")
        if source not in buckets or not isinstance(clarity, (int, float)):
            continue
        buckets[source].append(float(clarity))
    if not buckets["template"] and not buckets["model"]:
        print("not scored yet")
        return
    for source, values in buckets.items():
        if values:
            print(f"{source} n={len(values)} mean={sum(values) / len(values):.3f}")
        else:
            print(f"{source} n=0")


if __name__ == "__main__":
    main()
