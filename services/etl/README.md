# ETL (DuckDB + dbt)

| | |
|---|---|
| Owner | **BO1** |
| Module name | `etl` |
| Port | `8101` |
| Stack | DuckDB, dbt-core, dbt-duckdb, Jinja |
| LLM | no |

## Modes (`POST /v1/run`, field `mode`)

| mode | what it does |
|---|---|
| `run` | Load cleaned parquet into DuckDB and run the dbt project (staging + star schema marts + tests). Join SQL is rendered from the dataset YAML `relationships:`. |

## Run it

```bash
# from repo root
make venv SERVICE=etl                 # creates services/etl/.venv and installs deps
make run SERVICE=etl                  # uvicorn on :8101 (BIFLOW_MOCK=1 by default)
BIFLOW_MOCK=0 make run SERVICE=etl    # real handlers (raise NotImplementedError until you write them)
make test SERVICE=etl                 # contract test
```

## Definition of done for this module

See the spec sections for BO1 in `docs/BIFlow_Technical_Spec.md` (acceptance criteria and metrics are the definition of done).

## TODO checklist

- [ ] dbt_project/ skeleton is provided: fill staging + marts
- [ ] Jinja template that renders staging/join SQL from dataset YAML
- [ ] dbt tests (unique/not_null/relationships)
- [ ] Row reconciliation vs staging

## Folder map

```
app/main.py        wiring (do not change the endpoints)
app/handlers.py    YOUR CODE: one function per mode
mock/<mode>.json   fixture served when BIFLOW_MOCK=1 (keep it in sync with the real output shape)
prompts/           versioned prompts (see prompts/_template.yaml at repo root)
eval/              labelled sets + eval script used by POST /v1/eval
tests/             contract test (+ yours)
```
