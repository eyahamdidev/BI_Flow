# Ingest + Validate + Quality score

| | |
|---|---|
| Owner | **BO4** |
| Module name | `ingest_quality` |
| Port | `8104` |
| Stack | pandas, pyarrow, pandera, SQLAlchemy, httpx, duckdb |
| LLM | no |

## Modes (`POST /v1/run`, field `mode`)

| mode | what it does |
|---|---|
| `ingest` | Read the dataset source (`csv`, `sql`, `api` from `configs/datasets/<ds>.yaml`) and write raw parquet + manifest to `data/runs/<run_id>/00_ingest/`. |
| `validate` | Run pandera schemas generated dynamically from `expected_schema` in the dataset YAML. Returns `SCHEMA_MISMATCH` with a readable message `(table, column, expected, found)` on failure. |
| `score` | Deterministic 0-100 data quality score per table and overall across 5 dimensions: completeness, uniqueness, validity, consistency (FK integrity), and timeliness. `options.stage = before|after`. |

## Run it

```bash
# from repo root
make venv SERVICE=ingest_quality                 # creates services/ingest_quality/.venv and installs deps
make run SERVICE=ingest_quality                  # uvicorn on :8104 (BIFLOW_MOCK=1 by default)
BIFLOW_MOCK=0 make run SERVICE=ingest_quality    # real handlers
make test SERVICE=ingest_quality                 # contract & unit tests
```

### Connector Demos

Run the demo demonstrating CSV, SQL, and paginated REST API connectors:
```bash
python demo_connectors.py
```

### Reliability Evaluation & Benchmark

Run the reliability evaluation measuring schema error detection rate, score monotonicity, and reproducibility:
```bash
python eval/eval_reliability.py
```

## Definition of done for this module

All requirements from BO4 in `docs/BIFlow_Technical_Spec.md`:
- [x] Connector interface + CSVConnector (Olist)
- [x] SQLConnector (SQLite/DuckDB via SQLAlchemy)
- [x] APIConnector + local mock API server (`/mock_api`)
- [x] Pandera schemas generated dynamically from `expected_schema`
- [x] Quality score (5 dimensions, weights configured in YAML, FK integrity via relationships)
- [x] Reproducibility test (same input -> same SHA-256 hash)
- [x] Own CI: `.github/workflows/ci.yml`, `tests/contract/`, `tests/smoke/`, and ~100-row test fixtures (`tests/fixtures/olist/`)

## Folder map

```
app/
  connectors/        BaseConnector, CSVConnector, SQLConnector, APIConnector
  ingest.py          Ingestion pipeline, parquet serialization, SHA-256 manifest
  validation.py      Pandera schema construction & SCHEMA_MISMATCH reporting
  quality.py         5-dimension deterministic quality scoring engine
  mock_api.py        FastAPI mock server mounted at /mock_api for demoing API ingestion
  handlers.py        Dispatcher for ingest, validate, score
  main.py            FastAPI service wiring (port 8104)
mock/                Contract test fixtures for BIFLOW_MOCK=1
eval/                Reliability benchmark script & evaluation suite
tests/               Unit, contract, validation, quality, and reproducibility tests
```
