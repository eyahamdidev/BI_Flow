"""Label the fresh captions from the saved model text. Does not call a model."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REASONS = {
    1: "June and an increase are logged. Pricing adjustments are not.",
    2: "An increase versus the prior month is logged. Targeted promotions are not.",
    3: "A jump in AOV is the logged direction. High-value regions and a seasonal baseline are not.",
    4: "An upward change is logged. A loyalty tier is not.",
    5: "June and growth are logged. An internal forecast and a product bundle are not.",
    6: "A month-over-month lift is logged. Cross-sell initiatives are not.",
    7: "AOV climbing is the logged direction. A quarterly revenue target is not.",
    8: "A positive delta is logged. A UI redesign is not.",
    9: "A rise is the logged direction. Regional advertising, key states, and performance are not.",
    10: "An improvement is the logged direction. Competitors and flat growth are not.",
    11: "A gain is the logged direction. New payment options are not.",
    12: "June and an increase are logged. A summer campaign and record sales are not.",
    13: "A rise is the logged direction. Customer confidence and a trust-badge program are not.",
    14: "An uplift is the logged direction. Sustainability and an inventory decision are not.",
    15: "A month-over-month jump is logged. A logistics partnership is not.",
}


def main() -> None:
    raw = json.loads((HERE / "held_out_fresh_raw.json").read_text(encoding="utf-8"))
    items = []
    for row in json.loads(raw["raw"]):
        number = int(row["id"])
        items.append(
            {
                "id": f"f{number:02d}",
                "prose": row["prose"],
                "supported": False,
                "label_reason": REASONS[number],
            }
        )
    doc = {
        "model": raw["model"],
        "prompt_id": raw["prompt_id"],
        "source_case": raw["source_case"],
        "note": (
            "Written by gpt-oss-120b from the ex10 fact sheet only. "
            "The prompt asked for a claim the notes do not contain and did not mention the checker. "
            "Every caption was labelled unsupported by reading that sheet. "
            "This set has no supported control, so it does not measure false-reject."
        ),
        "fact_sheet": raw["fact_sheet"],
        "items": items,
    }
    (HERE / "held_out_fresh.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(items))


if __name__ == "__main__":
    main()
