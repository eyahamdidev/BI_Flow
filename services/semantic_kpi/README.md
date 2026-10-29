# Semantic & KPI (catalog, RAG)

| | |
|---|---|
| Owner | **BO5** |
| Module name | `semantic_kpi` |
| Port | `8105` |
| Stack | DuckDB (read), ChromaDB, pandas, embeddings via biflow_llm.embed() |
| LLM | yes (via `biflow_llm`, always with a fallback) |

## Modes (`POST /v1/run`, field `mode`)

| mode | what it does |
|---|---|
| `compute` | Execute each KPI `sql` from configs/kpis/<domain>.yaml on biflow.duckdb. Writes kpi_values.parquet + kpi_definitions.json. Every query is a lineage event. |
| `index` | Embed KPI definitions into Chroma collection kpi__<domain>; store embedder_name in metadata; rebuild on mismatch. |
| `map_question` | options.question -> KPI id via retrieval top-k (+ optional LLM pick from shortlist). Fallback: top-1. |
| `suggest_kpis` | New-dataset onboarding: schema -> retrieve similar KPIs -> LLM binds columns from the shortlist -> draft YAML for human review. Never auto-executed. |

## Run it

```bash
# from repo root
make venv SERVICE=semantic_kpi                 # creates services/semantic_kpi/.venv and installs deps
make run SERVICE=semantic_kpi                  # uvicorn on :8105 (BIFLOW_MOCK=1 by default)
BIFLOW_MOCK=0 make run SERVICE=semantic_kpi    # real handlers (raise NotImplementedError until you write them)
make test SERVICE=semantic_kpi                 # contract test
```

## Definition of done for this module

See the spec sections for BO5 in `docs/BIFlow_Technical_Spec.md` (acceptance criteria and metrics are the definition of done).

## TODO checklist

- [ ] KPI catalog schema + Olist KPIs in configs/kpis/ecommerce.yaml
- [ ] compute mode (month grain + dimension cuts)
- [ ] Chroma index with embedder_name guard
- [ ] map_question + suggest_kpis
- [ ] Second dataset onboarded with YAML only
- [ ] Retrieval benchmark (embedders, dense/BM25/hybrid, LLM on/off)

## Folder map

```
app/main.py        wiring (do not change the endpoints)
app/handlers.py    YOUR CODE: one function per mode
mock/<mode>.json   fixture served when BIFLOW_MOCK=1 (keep it in sync with the real output shape)
prompts/           versioned prompts (see prompts/_template.yaml at repo root)
eval/              labelled sets + eval script used by POST /v1/eval
tests/             contract test (+ yours)
```
