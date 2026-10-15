# Ingest + Validate + Quality score

| | |
|---|---|
| Owner | **BO4** |
| Module name | `ingest_quality` |
| Port | `8104` |
| Stack | pandas, pyarrow, pandera, SQLAlchemy, httpx |
| LLM | no |

## Modes (`POST /v1/run`, field `mode`)

| mode | what it does |
|---|---|
| `ingest` | Read the dataset source (csv|sql|api from configs/datasets/<ds>.yaml) and write raw parquet + manifest to data/runs/<run_id>/00_ingest/. |
| `validate` | Run pandera schemas generated from `expected_schema` in the dataset YAML. Return SCHEMA_MISMATCH with a readable message on failure. |
| `score` | Deterministic 0-100 data quality score per table and overall (completeness, uniqueness, validity, consistency, timeliness). options.stage = before|after. |

## Run it

```bash
# from repo root
make venv SERVICE=ingest_quality                 # creates services/ingest_quality/.venv and installs deps
make run SERVICE=ingest_quality                  # uvicorn on :8104 (BIFLOW_MOCK=1 by default)
BIFLOW_MOCK=0 make run SERVICE=ingest_quality    # real handlers (raise NotImplementedError until you write them)
make test SERVICE=ingest_quality                 # contract test
```

## Definition of done for this module

See the spec sections for BO4 in `docs/BIFlow_Technical_Spec.md` (acceptance criteria and metrics are the definition of done).

## TODO checklist

- [ ] Connector interface + CSVConnector (Olist)
- [ ] SQLConnector (SQLite/DuckDB demo)
- [ ] APIConnector + local mock API server
- [ ] pandera schemas from `expected_schema`
- [ ] Quality score (5 dimensions, weights in YAML)
- [ ] Reproducibility test (same input -> same hash)
- [ ] Own CI: .github/workflows/ci.yml, tests/contract, tests/smoke, fixtures

## Folder map

```
app/main.py        wiring (do not change the endpoints)
app/handlers.py    YOUR CODE: one function per mode
mock/<mode>.json   fixture served when BIFLOW_MOCK=1 (keep it in sync with the real output shape)
prompts/           versioned prompts (see prompts/_template.yaml at repo root)
eval/              labelled sets + eval script used by POST /v1/eval
tests/             contract test (+ yours)
```
