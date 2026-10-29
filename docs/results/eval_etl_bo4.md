# BIFlow evaluation results (2026-10-29T15:03:43, commit `a6f26be`)

| module | status | source | metric | value |
|---|---|---|---|---|
| etl | ok | real | kpi_checks_passed | 5/5 |
|  |  |  | kpi_checks.revenue_delivered.dbt | 151206.44 |
|  |  |  | kpi_checks.revenue_delivered.pandas | 151206.44 |
|  |  |  | kpi_checks.revenue_delivered.ok | True |
|  |  |  | kpi_checks.orders_delivered.dbt | 963.0 |
|  |  |  | kpi_checks.orders_delivered.pandas | 963.0 |
|  |  |  | kpi_checks.orders_delivered.ok | True |
|  |  |  | kpi_checks.avg_delivery_days.dbt | 12.456408 |
|  |  |  | kpi_checks.avg_delivery_days.pandas | 12.456408 |
|  |  |  | kpi_checks.avg_delivery_days.ok | True |
|  |  |  | kpi_checks.late_rate.dbt | 0.062305 |
|  |  |  | kpi_checks.late_rate.pandas | 0.062305 |
|  |  |  | kpi_checks.late_rate.ok | True |
|  |  |  | kpi_checks.avg_review_score.dbt | 4.156904 |
|  |  |  | kpi_checks.avg_review_score.pandas | 4.156904 |
|  |  |  | kpi_checks.avg_review_score.ok | True |
|  |  |  | dbt_tests_pass_rate | 0.962 |
|  |  |  | dbt_tests_failed | 0 |
|  |  |  | reconciliation_ok | True |
|  |  |  | seconds | 18.84 |
| ingest_quality | ok | real | schema_error_detection_rate | 1.0 |
|  |  |  | corrupted_inputs_tested | 20 |
|  |  |  | score_monotonicity | True |
|  |  |  | score_defect_correlation | -1.0 |
|  |  |  | baseline_score | 100.0 |
|  |  |  | severely_corrupted_score | 88.5 |
|  |  |  | reproducibility_rate | 1.0 |
