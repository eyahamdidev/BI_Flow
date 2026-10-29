# BIFlow

Multi-agent BI pipeline: **automated, transparent, traceable.** Raw CSVs in, a dashboard with explained KPIs,
insights and recommendations out. Pilot dataset: Olist Brazilian E-Commerce (Kaggle); second sector: bike sharing.
LLM = **any OpenAI-compatible API key or local Ollama**, chosen per developer in `.env`. Code computes every number;
the LLM only writes text from computed facts, and every number it writes is fact-checked.

Full design: [`docs/BIFlow_Technical_Spec.md`](docs/BIFlow_Technical_Spec.md) · rules: [`docs/RULES.md`](docs/RULES.md) ·
integration log: [`docs/INTEGRATION_NOTES.md`](docs/INTEGRATION_NOTES.md) · results: [`docs/results/`](docs/results/)

## Run it (Docker)

```bash
cp .env.example .env            # then set LLM_API_KEY (Groq or any OpenAI-compatible provider), or use Ollama
# data: put the 9 Olist CSVs in data/raw/olist/ (Kaggle olistbr/brazilian-ecommerce). The 1% sample is committed.
docker compose --profile core up -d --build
docker compose exec gateway python -m app.cli run --dataset olist_sample   # 1% sample, ~1-2 min
docker compose exec gateway python -m app.cli run --dataset olist          # full data, ~4 min
docker compose exec gateway python -m app.cli run --dataset bike_share     # second sector, config only
# dashboard: http://localhost:8501  (pick the run in the sidebar)
```

More commands (inside the gateway container, `docker compose exec gateway python -m app.cli ...`):

| command | what it does |
|---|---|
| `run --resume RUN_ID [--from STAGE]` | continue a run, or redo one stage and everything after it |
| `list` / `status RUN_ID` / `graph` | runs, a run's manifest, the pipeline graph (Mermaid) |
| `bench --dataset olist_sample --runs 5` | time-to-insight benchmark (p50/p95, cold vs cached LLM, resume, reproducibility) |
| `eval --all` | every module's `/v1/eval` in one results table |

Development: `docker-compose.override.yml` (loaded automatically) mounts each service's code, so after a code change
`docker compose restart <service>` is enough; rebuild only when a `requirements.lock` changes
(`python scripts/lock_all.py <service>`). If containers cannot reach the internet, see the proxy lines in `.env.example`.

## What happens in a run

```
ingest → validate_raw → profile → score_before → clean → profile_after → validate → score_after
      → etl (dbt on DuckDB) → kpi_compute → kpi_index → analyse → dashboard_config → lineage_graph → audit → summary
```

The gateway (LangGraph) is the only caller of modules. A failure jumps to the Auditor so it is still explained; the
config is frozen per run (`data/runs/<id>/dataset.yaml`), every stage writes lineage events, and the run manifest
labels each stage real / mock / seeded.

| BO | Module | Port | What it does |
|---|---|---|---|
| BO1 Time-to-insight | `gateway` + `etl` | 8000 / 8101 | LangGraph orchestration, resume, run summary; dbt staging generated from YAML + domain marts, tests, reconciliation |
| BO2 Trust (XAI) | `auditor` | 8102 | lineage graph, trace report, "Explain this KPI" with citations, fact-check |
| BO3 Cut manual cleaning | `profile_clean` | 8103 | profiling, rule + ML + advisory-LLM cleaning, before/after profile diff, review queue |
| BO4 Reliability | `ingest_quality` | 8104 | CSV / SQL / API ingest, pandera contracts, 0-100 quality score before/after |
| BO5 Scale across sectors | `semantic_kpi` | 8105 | KPI computation from the catalog (+ dimension cuts), KPI knowledge base (Chroma), question → KPI, new-dataset KPI drafts |
| BO6 Decide faster | `analyst` + `dashboard` | 8106 / 8501 | trends, anomalies, driver decomposition (sums to the change), rule-table recommendations, fact-checked narratives; Streamlit app |

New dataset = config only: `configs/datasets/<name>.yaml`, `configs/marts/<domain>/`, `configs/kpis/<domain>.yaml`,
`configs/recommendations/<domain>.yaml` (see `bike_share`).

## Layout

```
contracts/            frozen models, service kit, shared LLM helper
config/models.yaml    model names per profile (api | ollama | low_ram)
configs/              datasets/, marts/<domain>/, kpis/<domain>.yaml, recommendations/<domain>.yaml
services/<module>/    app/ · mock/ · eval/ · tests/ · Dockerfile · requirements.in / .lock
prompts/<module>/     versioned prompts (prompt library)
scripts/              lock_all.py, make_sample.py, dev_seed_run.py
tests/                fixtures (1% Olist sample), smoke test
docs/                 spec, rules, integration notes, manual baseline protocol, results
```
