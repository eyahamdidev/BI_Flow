# Fact sheets for the v7 faithfulness labels

Mark supported 1 only when every number, unit, label, period, and direction word matches this sheet and the sentence states nothing else. If unsure, mark 0 and write a note. Leave misleading_by_omission 1 when the published frames leave out a logged fact that changes the meaning.

The supported and omission cells are blank on purpose. This file does not label them.

## ex01

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Revenue went up by 1000 BRL between 2016-12 and 2017-01. The largest contribution came from SP (600 BRL). The second largest contribution came from RJ (400 BRL). Revenue is defined as: Total payments received for delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-01",
  "compare_to": "2016-12",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "BRL",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.revenue"
    ]
  },
  "drivers": {
    "kpi_id": "revenue",
    "period": "2017-01",
    "compare_to": "2016-12",
    "dimension": "customer_state",
    "total_delta": 1000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 600
      },
      {
        "dimension_value": "RJ",
        "delta": 400
      }
    ]
  },
  "insight_count": 0
}
```

## ex02

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Revenue went up by 2000 BRL between 2017-05 and 2017-06. The largest contribution came from MG (1200 BRL). The second largest contribution came from BA (800 BRL). Revenue is defined as: Total payments received for delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-06",
  "compare_to": "2017-05",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "BRL",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.revenue"
    ]
  },
  "drivers": {
    "kpi_id": "revenue",
    "period": "2017-06",
    "compare_to": "2017-05",
    "dimension": "customer_state",
    "total_delta": 2000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "MG",
        "delta": 1200
      },
      {
        "dimension_value": "BA",
        "delta": 800
      }
    ]
  },
  "insight_count": 0
}
```

## ex03

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Revenue went up by 3000 BRL between 2017-10 and 2017-11. The largest contribution came from PR (1800 BRL). The second largest contribution came from RS (1200 BRL). Revenue is defined as: Total payments received for delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-11",
  "compare_to": "2017-10",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "BRL",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.revenue"
    ]
  },
  "drivers": {
    "kpi_id": "revenue",
    "period": "2017-11",
    "compare_to": "2017-10",
    "dimension": "customer_state",
    "total_delta": 3000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "PR",
        "delta": 1800
      },
      {
        "dimension_value": "RS",
        "delta": 1200
      }
    ]
  },
  "insight_count": 0
}
```

## ex04

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Revenue went up by 4000 BRL between 2018-02 and 2018-03. The largest contribution came from SC (2400 BRL). The second largest contribution came from ES (1600 BRL). Revenue is defined as: Total payments received for delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2018-03",
  "compare_to": "2018-02",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "BRL",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.revenue"
    ]
  },
  "drivers": {
    "kpi_id": "revenue",
    "period": "2018-03",
    "compare_to": "2018-02",
    "dimension": "customer_state",
    "total_delta": 4000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SC",
        "delta": 2400
      },
      {
        "dimension_value": "ES",
        "delta": 1600
      }
    ]
  },
  "insight_count": 0
}
```

## ex05

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Orders went up by 5000 count between 2016-12 and 2017-01. The largest contribution came from SP (3000 count). The second largest contribution came from RJ (2000 count). Orders is defined as: Delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "orders",
  "period": "2017-01",
  "compare_to": "2016-12",
  "definition": {
    "kpi_id": "orders",
    "name": "Orders",
    "description": "Delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "count",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.orders"
    ]
  },
  "drivers": {
    "kpi_id": "orders",
    "period": "2017-01",
    "compare_to": "2016-12",
    "dimension": "customer_state",
    "total_delta": 5000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 3000
      },
      {
        "dimension_value": "RJ",
        "delta": 2000
      }
    ]
  },
  "insight_count": 0
}
```

## ex06

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Orders went up by 6000 count between 2017-05 and 2017-06. The largest contribution came from MG (3600 count). The second largest contribution came from BA (2400 count). Orders is defined as: Delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "orders",
  "period": "2017-06",
  "compare_to": "2017-05",
  "definition": {
    "kpi_id": "orders",
    "name": "Orders",
    "description": "Delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "count",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.orders"
    ]
  },
  "drivers": {
    "kpi_id": "orders",
    "period": "2017-06",
    "compare_to": "2017-05",
    "dimension": "customer_state",
    "total_delta": 6000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "MG",
        "delta": 3600
      },
      {
        "dimension_value": "BA",
        "delta": 2400
      }
    ]
  },
  "insight_count": 0
}
```

## ex07

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Orders went up by 7000 count between 2017-10 and 2017-11. The largest contribution came from PR (4200 count). The second largest contribution came from RS (2800 count). Orders is defined as: Delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "orders",
  "period": "2017-11",
  "compare_to": "2017-10",
  "definition": {
    "kpi_id": "orders",
    "name": "Orders",
    "description": "Delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "count",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.orders"
    ]
  },
  "drivers": {
    "kpi_id": "orders",
    "period": "2017-11",
    "compare_to": "2017-10",
    "dimension": "customer_state",
    "total_delta": 7000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "PR",
        "delta": 4200
      },
      {
        "dimension_value": "RS",
        "delta": 2800
      }
    ]
  },
  "insight_count": 0
}
```

## ex08

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Orders went up by 8000 count between 2018-02 and 2018-03. The largest contribution came from SC (4800 count). The second largest contribution came from ES (3200 count). Orders is defined as: Delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "orders",
  "period": "2018-03",
  "compare_to": "2018-02",
  "definition": {
    "kpi_id": "orders",
    "name": "Orders",
    "description": "Delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "count",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.orders"
    ]
  },
  "drivers": {
    "kpi_id": "orders",
    "period": "2018-03",
    "compare_to": "2018-02",
    "dimension": "customer_state",
    "total_delta": 8000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SC",
        "delta": 4800
      },
      {
        "dimension_value": "ES",
        "delta": 3200
      }
    ]
  },
  "insight_count": 0
}
```

## ex09

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Average order value went up by 9000 BRL between 2016-12 and 2017-01. The largest contribution came from SP (5400 BRL). The second largest contribution came from RJ (3600 BRL). Average order value is defined as: Revenue divided by delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "aov",
  "period": "2017-01",
  "compare_to": "2016-12",
  "definition": {
    "kpi_id": "aov",
    "name": "Average order value",
    "description": "Revenue divided by delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "BRL",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.aov"
    ]
  },
  "drivers": {
    "kpi_id": "aov",
    "period": "2017-01",
    "compare_to": "2016-12",
    "dimension": "customer_state",
    "total_delta": 9000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 5400
      },
      {
        "dimension_value": "RJ",
        "delta": 3600
      }
    ]
  },
  "insight_count": 0
}
```

## ex10

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Average order value went up by 10000 BRL between 2017-05 and 2017-06. The largest contribution came from MG (6000 BRL). The second largest contribution came from BA (4000 BRL). Average order value is defined as: Revenue divided by delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "aov",
  "period": "2017-06",
  "compare_to": "2017-05",
  "definition": {
    "kpi_id": "aov",
    "name": "Average order value",
    "description": "Revenue divided by delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "BRL",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.aov"
    ]
  },
  "drivers": {
    "kpi_id": "aov",
    "period": "2017-06",
    "compare_to": "2017-05",
    "dimension": "customer_state",
    "total_delta": 10000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "MG",
        "delta": 6000
      },
      {
        "dimension_value": "BA",
        "delta": 4000
      }
    ]
  },
  "insight_count": 0
}
```

## ex11

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Average order value went up by 11000 BRL between 2017-10 and 2017-11. The largest contribution came from PR (6600 BRL). The second largest contribution came from RS (4400 BRL). Average order value is defined as: Revenue divided by delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "aov",
  "period": "2017-11",
  "compare_to": "2017-10",
  "definition": {
    "kpi_id": "aov",
    "name": "Average order value",
    "description": "Revenue divided by delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "BRL",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.aov"
    ]
  },
  "drivers": {
    "kpi_id": "aov",
    "period": "2017-11",
    "compare_to": "2017-10",
    "dimension": "customer_state",
    "total_delta": 11000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "PR",
        "delta": 6600
      },
      {
        "dimension_value": "RS",
        "delta": 4400
      }
    ]
  },
  "insight_count": 0
}
```

## ex12

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Average order value went up by 12000 BRL between 2018-02 and 2018-03. The largest contribution came from SC (7200 BRL). The second largest contribution came from ES (4800 BRL). Average order value is defined as: Revenue divided by delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "aov",
  "period": "2018-03",
  "compare_to": "2018-02",
  "definition": {
    "kpi_id": "aov",
    "name": "Average order value",
    "description": "Revenue divided by delivered orders",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "BRL",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.aov"
    ]
  },
  "drivers": {
    "kpi_id": "aov",
    "period": "2018-03",
    "compare_to": "2018-02",
    "dimension": "customer_state",
    "total_delta": 12000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SC",
        "delta": 7200
      },
      {
        "dimension_value": "ES",
        "delta": 4800
      }
    ]
  },
  "insight_count": 0
}
```

## ex13

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Late-delivery rate went up by 13000 ratio between 2016-12 and 2017-01. The largest contribution came from SP (7800 ratio). The second largest contribution came from RJ (5200 ratio). Late-delivery rate is defined as: Share of orders delivered after the estimate The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "late_rate",
  "period": "2017-01",
  "compare_to": "2016-12",
  "definition": {
    "kpi_id": "late_rate",
    "name": "Late-delivery rate",
    "description": "Share of orders delivered after the estimate",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "ratio",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.late_rate"
    ]
  },
  "drivers": {
    "kpi_id": "late_rate",
    "period": "2017-01",
    "compare_to": "2016-12",
    "dimension": "customer_state",
    "total_delta": 13000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 7800
      },
      {
        "dimension_value": "RJ",
        "delta": 5200
      }
    ]
  },
  "insight_count": 0
}
```

## ex14

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Late-delivery rate went up by 14000 ratio between 2017-05 and 2017-06. The largest contribution came from MG (8400 ratio). The second largest contribution came from BA (5600 ratio). Late-delivery rate is defined as: Share of orders delivered after the estimate The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "late_rate",
  "period": "2017-06",
  "compare_to": "2017-05",
  "definition": {
    "kpi_id": "late_rate",
    "name": "Late-delivery rate",
    "description": "Share of orders delivered after the estimate",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "ratio",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.late_rate"
    ]
  },
  "drivers": {
    "kpi_id": "late_rate",
    "period": "2017-06",
    "compare_to": "2017-05",
    "dimension": "customer_state",
    "total_delta": 14000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "MG",
        "delta": 8400
      },
      {
        "dimension_value": "BA",
        "delta": 5600
      }
    ]
  },
  "insight_count": 0
}
```

## ex15

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Late-delivery rate went up by 15000 ratio between 2017-10 and 2017-11. The largest contribution came from PR (9000 ratio). The second largest contribution came from RS (6000 ratio). Late-delivery rate is defined as: Share of orders delivered after the estimate The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "late_rate",
  "period": "2017-11",
  "compare_to": "2017-10",
  "definition": {
    "kpi_id": "late_rate",
    "name": "Late-delivery rate",
    "description": "Share of orders delivered after the estimate",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "ratio",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.late_rate"
    ]
  },
  "drivers": {
    "kpi_id": "late_rate",
    "period": "2017-11",
    "compare_to": "2017-10",
    "dimension": "customer_state",
    "total_delta": 15000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "PR",
        "delta": 9000
      },
      {
        "dimension_value": "RS",
        "delta": 6000
      }
    ]
  },
  "insight_count": 0
}
```

## ex16

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Late-delivery rate went up by 16000 ratio between 2018-02 and 2018-03. The largest contribution came from SC (9600 ratio). The second largest contribution came from ES (6400 ratio). Late-delivery rate is defined as: Share of orders delivered after the estimate The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "late_rate",
  "period": "2018-03",
  "compare_to": "2018-02",
  "definition": {
    "kpi_id": "late_rate",
    "name": "Late-delivery rate",
    "description": "Share of orders delivered after the estimate",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "ratio",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.late_rate"
    ]
  },
  "drivers": {
    "kpi_id": "late_rate",
    "period": "2018-03",
    "compare_to": "2018-02",
    "dimension": "customer_state",
    "total_delta": 16000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SC",
        "delta": 9600
      },
      {
        "dimension_value": "ES",
        "delta": 6400
      }
    ]
  },
  "insight_count": 0
}
```

## ex17

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Average review score went up by 17000 score between 2016-12 and 2017-01. The largest contribution came from SP (10200 score). The second largest contribution came from RJ (6800 score). Average review score is defined as: Mean review score The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "avg_review_score",
  "period": "2017-01",
  "compare_to": "2016-12",
  "definition": {
    "kpi_id": "avg_review_score",
    "name": "Average review score",
    "description": "Mean review score",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "score",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.avg_review_score"
    ]
  },
  "drivers": {
    "kpi_id": "avg_review_score",
    "period": "2017-01",
    "compare_to": "2016-12",
    "dimension": "customer_state",
    "total_delta": 17000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 10200
      },
      {
        "dimension_value": "RJ",
        "delta": 6800
      }
    ]
  },
  "insight_count": 0
}
```

## ex18

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Average review score went up by 18000 score between 2017-05 and 2017-06. The largest contribution came from MG (10800 score). The second largest contribution came from BA (7200 score). Average review score is defined as: Mean review score The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "avg_review_score",
  "period": "2017-06",
  "compare_to": "2017-05",
  "definition": {
    "kpi_id": "avg_review_score",
    "name": "Average review score",
    "description": "Mean review score",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "score",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.avg_review_score"
    ]
  },
  "drivers": {
    "kpi_id": "avg_review_score",
    "period": "2017-06",
    "compare_to": "2017-05",
    "dimension": "customer_state",
    "total_delta": 18000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "MG",
        "delta": 10800
      },
      {
        "dimension_value": "BA",
        "delta": 7200
      }
    ]
  },
  "insight_count": 0
}
```

## ex19

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Average review score went up by 19000 score between 2017-10 and 2017-11. The largest contribution came from PR (11400 score). The second largest contribution came from RS (7600 score). Average review score is defined as: Mean review score The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "avg_review_score",
  "period": "2017-11",
  "compare_to": "2017-10",
  "definition": {
    "kpi_id": "avg_review_score",
    "name": "Average review score",
    "description": "Mean review score",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "score",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.avg_review_score"
    ]
  },
  "drivers": {
    "kpi_id": "avg_review_score",
    "period": "2017-11",
    "compare_to": "2017-10",
    "dimension": "customer_state",
    "total_delta": 19000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "PR",
        "delta": 11400
      },
      {
        "dimension_value": "RS",
        "delta": 7600
      }
    ]
  },
  "insight_count": 0
}
```

## ex20

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Average review score went up by 20000 score between 2018-02 and 2018-03. The largest contribution came from SC (12000 score). The second largest contribution came from ES (8000 score). Average review score is defined as: Mean review score The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates, drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "avg_review_score",
  "period": "2018-03",
  "compare_to": "2018-02",
  "definition": {
    "kpi_id": "avg_review_score",
    "name": "Average review score",
    "description": "Mean review score",
    "sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "unit": "score",
    "grain": "month"
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates",
      "drop_exact_duplicates"
    ],
    "dbt_models": [
      "dbt.fact_orders"
    ],
    "kpi_sql": "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders",
    "path_nodes": [
      "raw.orders",
      "clean.orders",
      "dbt.fact_orders",
      "kpi.avg_review_score"
    ]
  },
  "drivers": {
    "kpi_id": "avg_review_score",
    "period": "2018-03",
    "compare_to": "2018-02",
    "dimension": "customer_state",
    "total_delta": 20000,
    "contribution_count": 2,
    "contributions": [
      {
        "dimension_value": "SC",
        "delta": 12000
      },
      {
        "dimension_value": "ES",
        "delta": 8000
      }
    ]
  },
  "insight_count": 0
}
```

# synthetic

These 15 sheets cover shapes. They are not a sample for a rate.

## syn01_decrease

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Revenue went down by -800 BRL between 2017-03 and 2017-04. The largest contribution came from SP (-300 BRL). The second largest contribution came from RJ (-500 BRL). Revenue is defined as: Total payments received for delivered orders The figure comes from raw.orders; the logged cleaning steps are parse_dates.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-04",
  "compare_to": "2017-03",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "unit": "BRL"
  },
  "drivers": {
    "total_delta": -800,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": -300
      },
      {
        "dimension_value": "RJ",
        "delta": -500
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  }
}
```

## syn02_flat

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4. Offered: F1, F2, F3, F4, F5.

Published text:

Orders was unchanged by 0 orders between 2017-04 and 2017-05. The largest contribution came from SP (150 orders). The second largest contribution came from RJ (-150 orders). Orders is defined as: Count of delivered orders

Fact sheet:

```json
{
  "kpi_id": "orders",
  "period": "2017-05",
  "compare_to": "2017-04",
  "definition": {
    "kpi_id": "orders",
    "name": "Orders",
    "description": "Count of delivered orders",
    "unit": "orders"
  },
  "drivers": {
    "total_delta": 0,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 150
      },
      {
        "dimension_value": "RJ",
        "delta": -150
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  }
}
```

## syn03_one_driver

Language: en. Source: llm. Frames chosen: F1, F2, F4, F5. Offered: F1, F2, F4, F5.

Published text:

AOV went up by 250 BRL between 2017-05 and 2017-06. The largest contribution came from MG (250 BRL). AOV is defined as: Average payment value of delivered orders The figure comes from raw.order_payments; the logged cleaning steps are drop_exact_duplicates.

Fact sheet:

```json
{
  "kpi_id": "aov",
  "period": "2017-06",
  "compare_to": "2017-05",
  "definition": {
    "kpi_id": "aov",
    "name": "AOV",
    "description": "Average payment value of delivered orders",
    "unit": "BRL"
  },
  "drivers": {
    "total_delta": 250,
    "contributions": [
      {
        "dimension_value": "MG",
        "delta": 250
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "drop_exact_duplicates"
    ]
  }
}
```

## syn04_three_drivers

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Revenue went up by 900 BRL between 2017-06 and 2017-07. The largest contribution came from SP (500 BRL). The second largest contribution came from RJ (300 BRL). Revenue is defined as: Total payments received for delivered orders The figure comes from raw.orders, raw.order_payments; the logged cleaning steps are parse_dates.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-07",
  "compare_to": "2017-06",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "unit": "BRL"
  },
  "drivers": {
    "total_delta": 900,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 500
      },
      {
        "dimension_value": "RJ",
        "delta": 300
      },
      {
        "dimension_value": "BA",
        "delta": 100
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  }
}
```

## syn05_rule

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F6. Offered: F1, F2, F3, F4, F5, F6.

Published text:

Late rate went up by 4 pp between 2017-07 and 2017-08. The largest contribution came from SP (3 pp). The second largest contribution came from RJ (1 pp). Late rate is defined as: Share of orders delivered after the estimated date The logged rule for this change is late_delivery.

Fact sheet:

```json
{
  "kpi_id": "late_rate",
  "period": "2017-08",
  "compare_to": "2017-07",
  "definition": {
    "kpi_id": "late_rate",
    "name": "Late rate",
    "description": "Share of orders delivered after the estimated date",
    "unit": "pp"
  },
  "drivers": {
    "total_delta": 4,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 3
      },
      {
        "dimension_value": "RJ",
        "delta": 1
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  },
  "rule_id": "late_delivery"
}
```

## syn06_caveat

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F7. Offered: F1, F2, F3, F4, F5, F7.

Published text:

Review score went up by 2 points between 2017-08 and 2017-09. The largest contribution came from SP (2 points). The second largest contribution came from MG (0 points). Review score is defined as: Mean review score of delivered orders Caveat on record: Delivered orders only

Fact sheet:

```json
{
  "kpi_id": "avg_review_score",
  "period": "2017-09",
  "compare_to": "2017-08",
  "definition": {
    "kpi_id": "avg_review_score",
    "name": "Review score",
    "description": "Mean review score of delivered orders",
    "unit": "points",
    "caveats": "Delivered orders only"
  },
  "drivers": {
    "total_delta": 2,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 2
      },
      {
        "dimension_value": "MG",
        "delta": 0
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.order_reviews"
    ],
    "cleaning_rules": [
      "drop_exact_duplicates"
    ]
  }
}
```

## syn07_both

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4, F6. Offered: F1, F2, F3, F4, F5, F6, F7.

Published text:

Revenue went up by 700 BRL between 2017-09 and 2017-10. The largest contribution came from SP (400 BRL). The second largest contribution came from RJ (300 BRL). Revenue is defined as: Total payments received for delivered orders The logged rule for this change is late_delivery.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-10",
  "compare_to": "2017-09",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "unit": "BRL",
    "caveats": "Delivered orders only"
  },
  "drivers": {
    "total_delta": 700,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 400
      },
      {
        "dimension_value": "RJ",
        "delta": 300
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  },
  "rule_id": "late_delivery"
}
```

## syn08_no_lineage

Language: en. Source: llm. Frames chosen: F1, F2, F3, F4. Offered: F1, F2, F3, F4.

Published text:

Orders went up by 40 orders between 2017-10 and 2017-11. The largest contribution came from BA (25 orders). The second largest contribution came from MG (15 orders). Orders is defined as: Count of delivered orders

Fact sheet:

```json
{
  "kpi_id": "orders",
  "period": "2017-11",
  "compare_to": "2017-10",
  "definition": {
    "kpi_id": "orders",
    "name": "Orders",
    "description": "Count of delivered orders",
    "unit": "orders"
  },
  "drivers": {
    "total_delta": 40,
    "contributions": [
      {
        "dimension_value": "BA",
        "delta": 25
      },
      {
        "dimension_value": "MG",
        "delta": 15
      }
    ]
  }
}
```

## syn09_empty

Language: en. Source: abstain. Frames chosen: none. Offered: none.

Published text:

not enough logged information

Fact sheet:

```json
{}
```

## syn10_decrease_fr

Language: fr. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Revenue a en baisse de -800 BRL entre 2017-03 et 2017-04. La plus grande contribution vient de SP (-300 BRL). La deuxième plus grande contribution vient de RJ (-500 BRL). Revenue est défini comme : Total payments received for delivered orders Le chiffre provient de raw.orders ; les étapes de nettoyage enregistrées sont parse_dates.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-04",
  "compare_to": "2017-03",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "unit": "BRL"
  },
  "drivers": {
    "total_delta": -800,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": -300
      },
      {
        "dimension_value": "RJ",
        "delta": -500
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  }
}
```

## syn11_flat_fr

Language: fr. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Orders a inchangé de 0 orders entre 2017-04 et 2017-05. La plus grande contribution vient de SP (150 orders). La deuxième plus grande contribution vient de RJ (-150 orders). Orders est défini comme : Count of delivered orders Le chiffre provient de raw.orders ; les étapes de nettoyage enregistrées sont parse_dates.

Fact sheet:

```json
{
  "kpi_id": "orders",
  "period": "2017-05",
  "compare_to": "2017-04",
  "definition": {
    "kpi_id": "orders",
    "name": "Orders",
    "description": "Count of delivered orders",
    "unit": "orders"
  },
  "drivers": {
    "total_delta": 0,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 150
      },
      {
        "dimension_value": "RJ",
        "delta": -150
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  }
}
```

## syn12_rule_fr

Language: fr. Source: llm. Frames chosen: F1, F2, F3, F4, F6. Offered: F1, F2, F3, F4, F5, F6.

Published text:

Late rate a en hausse de 4 pp entre 2017-07 et 2017-08. La plus grande contribution vient de SP (3 pp). La deuxième plus grande contribution vient de RJ (1 pp). Late rate est défini comme : Share of orders delivered after the estimated date La règle enregistrée pour ce changement est late_delivery.

Fact sheet:

```json
{
  "kpi_id": "late_rate",
  "period": "2017-08",
  "compare_to": "2017-07",
  "definition": {
    "kpi_id": "late_rate",
    "name": "Late rate",
    "description": "Share of orders delivered after the estimated date",
    "unit": "pp"
  },
  "drivers": {
    "total_delta": 4,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 3
      },
      {
        "dimension_value": "RJ",
        "delta": 1
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  },
  "rule_id": "late_delivery"
}
```

## syn13_caveat_fr

Language: fr. Source: llm. Frames chosen: F1, F2, F3. Offered: F1, F2, F3, F4, F5, F7.

Published text:

Review score a en hausse de 2 points entre 2017-08 et 2017-09. La plus grande contribution vient de SP (2 points). La deuxième plus grande contribution vient de MG (0 points).

Fact sheet:

```json
{
  "kpi_id": "avg_review_score",
  "period": "2017-09",
  "compare_to": "2017-08",
  "definition": {
    "kpi_id": "avg_review_score",
    "name": "Review score",
    "description": "Mean review score of delivered orders",
    "unit": "points",
    "caveats": "Delivered orders only"
  },
  "drivers": {
    "total_delta": 2,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 2
      },
      {
        "dimension_value": "MG",
        "delta": 0
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.order_reviews"
    ],
    "cleaning_rules": [
      "drop_exact_duplicates"
    ]
  }
}
```

## syn14_three_fr

Language: fr. Source: llm. Frames chosen: F1, F2, F3, F4, F5. Offered: F1, F2, F3, F4, F5.

Published text:

Revenue a en hausse de 900 BRL entre 2017-06 et 2017-07. La plus grande contribution vient de SP (500 BRL). La deuxième plus grande contribution vient de RJ (300 BRL). Revenue est défini comme : Total payments received for delivered orders Le chiffre provient de raw.orders, raw.order_payments ; les étapes de nettoyage enregistrées sont parse_dates.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-07",
  "compare_to": "2017-06",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "unit": "BRL"
  },
  "drivers": {
    "total_delta": 900,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 500
      },
      {
        "dimension_value": "RJ",
        "delta": 300
      },
      {
        "dimension_value": "BA",
        "delta": 100
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders",
      "raw.order_payments"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  }
}
```

## syn15_both_fr

Language: fr. Source: llm. Frames chosen: F1, F2, F3, F4, F6. Offered: F1, F2, F3, F4, F5, F6, F7.

Published text:

Revenue a en hausse de 700 BRL entre 2017-09 et 2017-10. La plus grande contribution vient de SP (400 BRL). La deuxième plus grande contribution vient de RJ (300 BRL). Revenue est défini comme : Total payments received for delivered orders La règle enregistrée pour ce changement est late_delivery.

Fact sheet:

```json
{
  "kpi_id": "revenue",
  "period": "2017-10",
  "compare_to": "2017-09",
  "definition": {
    "kpi_id": "revenue",
    "name": "Revenue",
    "description": "Total payments received for delivered orders",
    "unit": "BRL",
    "caveats": "Delivered orders only"
  },
  "drivers": {
    "total_delta": 700,
    "contributions": [
      {
        "dimension_value": "SP",
        "delta": 400
      },
      {
        "dimension_value": "RJ",
        "delta": 300
      }
    ]
  },
  "lineage": {
    "found": true,
    "raw_tables": [
      "raw.orders"
    ],
    "cleaning_rules": [
      "parse_dates"
    ]
  },
  "rule_id": "late_delivery"
}
```

