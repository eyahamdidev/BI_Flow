"""Shared limits for the auditor. Budgets match the technical spec (section 2.3 and 2.7)."""
import os

ABSTAIN = "not enough logged information"

# Deadlines for the LLM prose, checked between calls. They must be SHORTER than the gateway's HTTP budget for the stage
# (audit 120 s, explain 45 s) so that a call still in flight at the deadline cannot push the answer past it.
AUDIT_TIMEOUT_S = int(os.getenv("AUDIT_LLM_BUDGET_S", "80"))
EXPLAIN_TIMEOUT_S = int(os.getenv("EXPLAIN_LLM_BUDGET_S", "25"))
MAX_LLM_SECTIONS = 8
WRITER_TEMPERATURE = 0.2

AUDITOR_STEPS = ("build_lineage_graph", "write_trace_report", "explain_kpi")

# Fallback when the other modules' /v1/meta endpoints cannot be reached.
# Kept aligned with each service's create_app(lineage_steps=...) and checked by a test.
STATIC_LINEAGE_STEPS = {  # fallback only: the gateway passes the live lists (options.registered_steps)
    "ingest_quality": ['ingest_csv', 'ingest_sql', 'ingest_api', 'validate_schema', 'score'],
    "profile_clean": ['category_map', 'category_mapping_fixes', 'clean_table', 'dedupe', 'dedupe_geolocation', 'detect_outliers', 'drop_exact_duplicates', 'flag_impossible_values', 'impute_categorical', 'impute_numeric', 'llm_advisory', 'null_strategy', 'parse_dates', 'profile_diff', 'profile_tables', 'rename_columns', 'sentinel_to_null', 'standardise', 'translate_category_names', 'trim_strings', 'type_guard_block'],
    "etl": ['load_raw', 'dbt_staging', 'dbt_intermediate', 'dbt_marts', 'dbt_tests', 'reconcile'],
    "semantic_kpi": ['compute_kpi', 'compute_kpi_cut', 'index_kpis'],
    "analyst": ['detect_trends', 'detect_anomalies', 'decompose_drivers', 'match_recommendations', 'write_narratives', 'dashboard_config'],
}

# The step list the eval fixture (eval/events.jsonl) was written against. The eval measures the completeness CHECK on a
# known fixture, so it keeps its own registry; STATIC_LINEAGE_STEPS above tracks the real modules and grows with them.
EVAL_LINEAGE_STEPS = {
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
