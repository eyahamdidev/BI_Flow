# BO4 Technical Report: Improving Pipeline Reliability

**Author / Owner:** BO4 (Ingest, Validate, Quality Score, CI & Testing)  
**Module:** `ingest_quality` (Port 8104)  
**Status:** Completed & Validated  

---

## 1. Reliability Architecture & Design

In an automated end-to-end business intelligence pipeline, downstream calculations (ETL, KPI aggregation, machine learning, and executive dashboards) can only be as trustworthy as the data entering the system. Data errors that go unmonitored early cause cascading failures that manifest hours later as broken dbt runs, silent metric corruptions, or skewed decision-making.

BO4 guarantees reliability through four architectural pillars:

```
[Raw Sources: CSV | SQL | REST API]
                 │
                 ▼
       ┌───────────────────┐
       │     Ingestion     │ ──► SHA-256 Manifest + Parquet Storage
       └───────────────────┘
                 │
                 ▼
       ┌───────────────────┐
       │   Quality Score   │ ──► 5-Dimension Score (Before Cleaning)
       └───────────────────┘
                 │
                 ▼
       ┌───────────────────┐
       │ Schema Validation │ ──► Pandera Declarative Contracts
       └───────────────────┘     (Returns SCHEMA_MISMATCH on failure)
```

1. **Pluggable Source Ingestion (`mode: ingest`)**:
   - A unified `BaseConnector` interface abstracts the physical storage layer.
   - Three production-grade connectors implemented:
     - `CSVConnector`: Configurable directory / filename mappings with high-performance Pandas / PyArrow chunking.
     - `SQLConnector`: SQLAlchemy-backed engine supporting SQLite, DuckDB, PostgreSQL, MySQL with automatic connection disposal and query pushdown.
     - `APIConnector`: Resilient HTTP client supporting pagination (`page`, `page_size`, `total`, `has_next`) and rate-limit backoff.
   - All ingested tables are converted to Parquet at `data/runs/<run_id>/00_ingest/` with bit-level SHA-256 checksums, row counts, and an ingestion `manifest.json`.

2. **Declarative Schema Contracts (`mode: validate`)**:
   - Input contracts after ingestion and output contracts after data cleaning.
   - Converts the dataset YAML's `expected_schema` dynamically into **Pandera** `DataFrameSchema` instances.
   - Schema enforcement is strict: any missing column, invalid data type, or unauthorized `NULL` value in a non-nullable field halts the stage immediately with a structured `SCHEMA_MISMATCH` error code and human-readable diagnostics: `(table, column, expected, found)`.

3. **Multi-Dimensional Deterministic Quality Scoring (`mode: score`)**:
   - Computes a deterministic 0–100 score per table and dataset-wide across five fundamental dimensions defined in ISO/IEC 25012:
     - **Completeness ($w=0.30$)**: Measures missing/null values:
       $$\text{Completeness} = 100 \times \left(1 - \frac{\text{null\_cells}}{\text{total\_cells}}\right)$$
     - **Uniqueness ($w=0.20$)**: Evaluates exact duplicate rows and primary key uniqueness:
       $$\text{Uniqueness} = 100 \times \left(1 - \frac{\text{duplicate\_rows}}{\text{total\_rows}}\right)$$
     - **Validity ($w=0.20$)**: Checks adherence to domain constraints (non-negative prices, valid status enums, parseable datetimes).
     - **Consistency / FK Integrity ($w=0.20$)**: Evaluates referential integrity against the YAML `relationships` block:
       $$\text{Consistency} = 100 \times \left(1 - \frac{\text{orphan\_foreign\_keys}}{\text{total\_child\_rows}}\right)$$
     - **Timeliness ($w=0.10$)**: Validates chronological coherence (e.g. delivery date cannot precede order purchase date).
   - The orchestrator executes `score` twice (`stage: before` on raw ingest and `stage: after` on cleaned data), quantifying data cleaning gains transparently.

4. **Reproducibility Guarantee**:
   - Given the same input data and configuration, repeat executions produce 100% bit-for-bit identical SHA-256 Parquet file hashes and quality scores ($r = 1.0$).

---

## 2. Test Strategy & CI Ownership

BO4 owns the repository-wide testing and continuous integration infrastructure:

1. **Test Fixtures (`tests/fixtures/olist/`)**:
   - Consistent ~100-row sample of the Olist e-commerce dataset generated with referential integrity preserved across all 9 relational tables.
   - Enables ultra-fast unit testing (<1 second) and contract validation without loading 1.5M rows into memory.

2. **Contract Testing (`tests/contract/`)**:
   - Verifies all registered microservices (`ingest_quality`, `profile_clean`, `etl`, `semantic_kpi`, `analyst`, `auditor`) against frozen JSONSchemas (`RunResponse.json`, `RunRequest.json`, `MetaResponse.json`, `EvalResponse.json`).
   - Ensures error envelopes and HTTP status codes (`400 BAD_INPUT`, `500 INTERNAL`, etc.) strictly conform to spec.

3. **Smoke Testing (`tests/smoke/`)**:
   - End-to-end simulation of the full multi-agent pipeline using mock services and `FAKE_LLM=1`.
   - Verified execution finishes in under 60 seconds.

4. **CI Workflow (`.github/workflows/ci.yml`)**:
   - Automated GitHub Actions pipeline executing:
     - `lint`: Ruff code style checks.
     - `contracts-and-registry`: Contract validation against JSON schemas + prompt registry schema validation.
     - `service-tests`: Service-isolated unit test matrix.
     - `smoke`: End-to-end mock pipeline smoke test.

---

## 3. Benchmark & Experimental Results

The reliability benchmark (`eval/eval_reliability.py`) produced the following empirical results:

| Metric | Result | Benchmark Target | Status |
|---|---|---|---|
| **Schema Error Detection Rate** | **100% (20/20)** | $\ge 95\%$ | **Exceeded** |
| **Score Monotonic Sensitivity** | **True** | Monotonic decrease on defect injection | **Passed** |
| **Defect Correlation ($r$)** | **$-1.000$** | Near $-1.0$ | **Optimal** |
| **Reproducibility Rate** | **100% (1.00)** | $1.00$ (identical file & metric hashes) | **Passed** |
| **Baseline Quality Score** | **100.0 / 100** | Reference clean data | **Passed** |
| **Corrupted Quality Score** | **88.5 / 100** | Proportional degradation | **Passed** |
| **End-to-End Smoke Test** | **57.70 s** | $< 120$ s | **Passed** |
| **Contract Test Pass Rate** | **100% (15/15)** | 100% | **Passed** |

