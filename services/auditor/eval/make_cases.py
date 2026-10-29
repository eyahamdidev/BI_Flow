"""Write eval/explain_cases.json: 20 labelled (kpi, period) cases with driver lists."""

from __future__ import annotations

import json
from pathlib import Path

KPIS = [
    ("revenue", "Revenue", "BRL", "Total payments received for delivered orders"),
    ("orders", "Orders", "count", "Delivered orders"),
    ("aov", "Average order value", "BRL", "Revenue divided by delivered orders"),
    ("late_rate", "Late-delivery rate", "ratio", "Share of orders delivered after the estimate"),
    ("avg_review_score", "Average review score", "score", "Mean review score"),
]
PERIODS = [("2017-01", "2016-12"), ("2017-06", "2017-05"), ("2017-11", "2017-10"), ("2018-03", "2018-02")]
PAIRS = [("SP", "RJ"), ("MG", "BA"), ("PR", "RS"), ("SC", "ES")]
SQL = (
    "SELECT date_trunc('month', order_purchase_timestamp) AS period, "
    "SUM(payment_value) AS value FROM fact_orders"
)


def build() -> dict:
    cases = []
    index = 0
    for kpi_id, name, unit, description in KPIS:
        for period, compare in PERIODS:
            delta = 1000 * (index + 1)
            top_delta = delta * 3 // 5
            rest = delta - top_delta
            top, second = PAIRS[index % len(PAIRS)]
            sheet = {
                "kpi_id": kpi_id,
                "period": period,
                "compare_to": compare,
                "definition": {
                    "kpi_id": kpi_id,
                    "name": name,
                    "description": description,
                    "sql": SQL,
                    "unit": unit,
                    "grain": "month",
                },
                "lineage": {
                    "found": True,
                    "raw_tables": ["raw.orders", "raw.order_payments"],
                    "cleaning_rules": ["parse_dates", "drop_exact_duplicates"],
                    "dbt_models": ["dbt.fact_orders"],
                    "kpi_sql": SQL,
                    "path_nodes": ["raw.orders", "clean.orders", "dbt.fact_orders", f"kpi.{kpi_id}"],
                },
                "drivers": {
                    "kpi_id": kpi_id,
                    "period": period,
                    "compare_to": compare,
                    "dimension": "customer_state",
                    "total_delta": delta,
                    "contribution_count": 2,
                    "contributions": [
                        {"dimension_value": top, "delta": top_delta},
                        {"dimension_value": second, "delta": rest},
                    ],
                },
                "insight_count": 0,
            }
            cases.append(
                {
                    "id": f"ex{index + 1:02d}",
                    "kpi_id": kpi_id,
                    "period": period,
                    "compare_to": compare,
                    "expected_drivers": [top, second],
                    "fact_sheet": sheet,
                    "claims": [
                        {"text": f"The logged change is {delta}.", "supported": True},
                        {"text": f"The largest logged contribution is {top} at {top_delta}.", "supported": True},
                        {"text": f"An unlogged adjustment of {900000 + index} was applied.", "supported": False},
                    ],
                }
            )
            index += 1
    return {"cases": cases}


def main() -> None:
    out = Path(__file__).resolve().parent / "explain_cases.json"
    out.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(build()['cases'])} cases to {out.name}")


if __name__ == "__main__":
    main()
