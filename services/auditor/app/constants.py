"""Shared limits for the auditor. Budgets match the technical spec (section 2.3 and 2.7)."""

ABSTAIN = "not enough logged information"

AUDIT_TIMEOUT_S = 120
EXPLAIN_TIMEOUT_S = 30
MAX_LLM_SECTIONS = 8
WRITER_TEMPERATURE = 0.2

AUDITOR_STEPS = ("build_lineage_graph", "write_trace_report", "explain_kpi")

# Fallback when the other modules' /v1/meta endpoints cannot be reached.
# Kept aligned with each service's create_app(lineage_steps=...) and checked by a test.
STATIC_LINEAGE_STEPS = {
    "ingest_quality": ["ingest_csv", "validate_schema", "score"],
    "profile_clean": ["profile_tables", "translate_category_names", "impute_product_weight"],
    "etl": ["dbt_staging", "dbt_marts"],
    "semantic_kpi": ["compute_kpi"],
    "analyst": ["detect_anomalies"],
}

MODULE_PORTS = {
    "etl": 8101,
    "profile_clean": 8103,
    "ingest_quality": 8104,
    "semantic_kpi": 8105,
    "analyst": 8106,
}
