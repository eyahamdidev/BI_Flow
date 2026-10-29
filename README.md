# BIFlow

Multi-agent BI pipeline: **automated, transparent, traceable.** Pilot dataset: Olist (Kaggle). Local-first and open source.
LLM = **Ollama (local) or any OpenAI-compatible API key**, chosen per developer in `.env`.

Full design: [`docs/BIFlow_Technical_Spec.md`](docs/BIFlow_Technical_Spec.md). Rules in one page: [`docs/RULES.md`](docs/RULES.md).

## Quick start (everything runs on mocks out of the box)

```bash
make init                       # creates .env and a venv per service (a few minutes)
# edit .env: Ollama (default) or an API key. See .env.example
make dev                        # starts the 7 backend services (mocks)
(cd services/gateway && .venv/bin/python -m app.cli run --dataset olist)   # runs the whole pipeline on mocks
make run SERVICE=dashboard      # http://localhost:8501 (demo fixtures, or pick a real run)
make stop
```

Docker instead: `make up` (profile `core`), add `--profile ollama` for a local Ollama container.

Ollama: `ollama pull qwen2.5:7b-instruct llama3.2:3b nomic-embed-text` (8 GB RAM: set `BIFLOW_PROFILE=low_ram`).

Dataset: download Olist from Kaggle into `data/raw/olist/` (9 CSVs, gitignored).

## Who owns what

| BO | Owner | Module (folder) | Port |
|---|---|---|---|
| BO1 Time-to-insight | | `services/gateway` + `services/etl` | 8000 / 8101 |
| BO2 Trust (XAI) | | `services/auditor` | 8102 |
| BO3 Cut manual cleaning | | `services/profile_clean` | 8103 |
| BO4 Reliability | | `services/ingest_quality` + CI/tests | 8104 |
| BO5 Scale across sectors | | `services/semantic_kpi` + `configs/kpis` | 8105 |
| BO6 Decide faster | | `services/analyst` + `services/dashboard` | 8106 / 8501 |

## Layout

```
contracts/            frozen models, service kit, LLM helper (pip install -e contracts)
config/models.yaml    model names per profile (ollama | low_ram | api)
configs/              datasets/olist.yaml, kpis/ecommerce.yaml, recommendations/
services/<module>/    app/ (main.py, handlers.py) · mock/ · prompts/ · eval/ · tests/ · Dockerfile · requirements.in
services/gateway/     pipeline runner + graph.yaml (the only caller of modules)
services/dashboard/   Streamlit: data layer · api layer · tabs · components · fixtures
prompts/_template.yaml   prompt library format
tests/smoke/          end-to-end on mocks (CI)
docs/                 spec, rules, how to add a service, branching
```

## Status of the skeleton

Every module serves **mock** responses on the real endpoints and passes its contract test. The gateway runs the full pipeline
(with retries, `--resume`, lineage writer, run manifest, "failure still runs the Auditor"). Real handlers are `NotImplementedError`
stubs with the spec's TODO list in each service README. Work: replace stubs, then set `BIFLOW_MOCK=0` for your module.
