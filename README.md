# BIFlow

Multi-agent BI pipeline: **automated, transparent, traceable.** Raw CSV files go in; a dashboard comes out with KPIs,
the reasons behind each change, insights, recommendations and a full audit trail of every transformation.
Code computes every number. An LLM (optional) only writes text from those numbers, and every number it writes is
checked against the facts.

---

## Try it in 5 minutes

**You need:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running) and [Git](https://git-scm.com/downloads).
Nothing else: no Python, no database, no data download. The demo data is in the repository.

```bash
git clone https://github.com/eyahamdidev/BI_Flow.git
cd BI_Flow
git checkout bo1/foundation        # the integrated branch (until it is merged into main)
```

Then start everything with **one command**:

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `powershell -ExecutionPolicy Bypass -File start.ps1` | `./start.sh` |

The script:
1. checks that Docker is running,
2. creates your `.env` and asks for an **optional** LLM API key (press Enter to skip),
3. builds and starts the 8 services (**first time: 5-15 minutes**, mostly downloads; afterwards seconds),
4. runs the full pipeline on the demo data (1% of the Olist e-commerce dataset, about 1-2 minutes),
5. opens the dashboard at **http://localhost:8501**. Pick the run in the left sidebar.

**Without an API key** everything still works: the LLM steps use their built-in templates instead.
**With a key** the summaries, narratives and explanations are written by the LLM. A free key:
[Groq](https://console.groq.com/keys) (or any OpenAI-compatible provider: set `LLM_BASE_URL` and `LLM_API_KEY` in `.env`).

### More datasets

| command (Windows: `.\start.ps1 ...`, macOS/Linux: `./start.sh ...`) | what runs |
|---|---|
| `start.ps1 -Dataset bike_share` / `./start.sh bike_share` | a second sector (urban bike sharing), onboarded with config files only |
| `start.ps1 -Full` / `./start.sh --full` | the **full** Olist dataset (100k orders): downloads it from Kaggle (~45 MB), ~4 minutes |
| `start.ps1 -Stop` / `./start.sh --stop` | stop everything |

If the Kaggle download is blocked on your network, download
[olistbr/brazilian-ecommerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) by hand, unzip the 9 CSV
files into `data/raw/olist/`, and run `start.ps1 -Dataset olist` / `./start.sh olist`.

### Test with your own data (same structure as Olist)

In the dashboard sidebar, **Add a dataset**: choose the dataset it looks like (`olist`), give it a name, upload the CSV
files (same file names and columns; the sidebar lists them), then **Start a new run** with the new dataset selected.
The files are checked first (all files present, all columns present) and stored locally in `data/uploads/<name>/`.
A 5-row test set is ready in [`tests/fixtures/upload_demo/`](tests/fixtures/upload_demo/).

### What to look at in the dashboard

| tab | what it shows |
|---|---|
| Overview | run summary, one tile per KPI (latest complete month), pipeline stages |
| KPI explorer | trends, breakdowns, and **"why did it move?"**: the change split by segment (parts sum to the total) |
| Insights and actions | trends, anomalies (e.g. the Black Friday spike), recommendations from the rule table |
| Data quality | quality score before / after cleaning, profile diff |
| Lineage | graph from raw tables to KPIs, and the Auditor's trace report |
| Explain | ask in your own words ("why did sales drop?"): a fact-checked explanation with citations |

### Troubleshooting

- **Build fails with a network error**: run the start script again (downloads resume from the cache).
- **"Docker is not running"**: start Docker Desktop and wait until it says "running".
- **A port is already used** (8000, 8101-8106, 8501): stop the other program, or `start.ps1 -Stop` an older BIFlow.
- **Containers cannot reach the internet** (LLM calls fail although the key is right): if `docker info` shows an
  HTTP proxy, uncomment the two proxy lines in `.env` and run the start script again.
- Logs of one service: `docker compose logs -f gateway` (or etl, auditor, profile_clean, ingest_quality, semantic_kpi, analyst, dashboard).

---

## Command line (optional)

All commands run inside the gateway container: `docker compose exec gateway python -m app.cli <command>`

| command | what it does |
|---|---|
| `run --dataset olist_sample` | run the pipeline (datasets: `olist_sample`, `bike_share`, `olist`) |
| `run --resume RUN_ID [--from STAGE]` | continue a run, or redo one stage and everything after it |
| `list` / `status RUN_ID` / `graph` | runs, one run's manifest, the pipeline graph (Mermaid) |
| `bench --dataset olist_sample --runs 5` | time-to-insight benchmark (p50/p95, cold vs cached LLM, resume, reproducibility) |
| `eval --all` | every module's self-evaluation in one results table |

## How it works

```
ingest → validate_raw → profile → score_before → clean → profile_after → validate → score_after
      → etl (dbt on DuckDB) → kpi_compute → kpi_index → analyse → dashboard_config → lineage_graph → audit → summary
```

The gateway (LangGraph) is the only component that calls the modules. If a stage fails, the run jumps to the Auditor
so the failure is still explained. Each run freezes its exact config (`data/runs/<id>/dataset.yaml`), every stage
writes lineage events, and the run manifest labels each stage real / mock / seeded.

| BO | Module | Port | What it does |
|---|---|---|---|
| BO1 Time-to-insight | `gateway` + `etl` | 8000 / 8101 | orchestration, resume, run summary; dbt staging generated from YAML + domain marts, tests, reconciliation |
| BO2 Trust (XAI) | `auditor` | 8102 | lineage graph, trace report, "Explain this KPI" with citations, fact-check |
| BO3 Cut manual cleaning | `profile_clean` | 8103 | profiling, rule + ML + advisory-LLM cleaning, before/after profile, review queue |
| BO4 Reliability | `ingest_quality` | 8104 | CSV / SQL / API ingest, schema contracts, 0-100 quality score before/after |
| BO5 Scale across sectors | `semantic_kpi` | 8105 | KPIs from a catalog (+ breakdowns), KPI search, question → KPI, KPI drafts for new datasets |
| BO6 Decide faster | `analyst` + `dashboard` | 8106 / 8501 | trends, anomalies, driver decomposition, rule-based recommendations, narratives; Streamlit app |

**A new dataset is config only:** `configs/datasets/<name>.yaml`, `configs/marts/<domain>/`, `configs/kpis/<domain>.yaml`,
`configs/recommendations/<domain>.yaml`. See `bike_share` for a complete example.

Results and evidence: [`docs/results/`](docs/results/) (benchmark, evaluations) · design: [`docs/BIFlow_Technical_Spec.md`](docs/BIFlow_Technical_Spec.md) ·
rules: [`docs/RULES.md`](docs/RULES.md) · integration log: [`docs/INTEGRATION_NOTES.md`](docs/INTEGRATION_NOTES.md) ·
manual baseline protocol: [`docs/manual_baseline.md`](docs/manual_baseline.md) ·
future work: [`docs/FUTURE_WORK.md`](docs/FUTURE_WORK.md)

## For developers

- `docker-compose.override.yml` (loaded automatically) mounts each service's code: after a code change,
  `docker compose restart <service>` is enough. Rebuild only when a `requirements.lock` changes
  (`python scripts/lock_all.py <service>`, needs `pip install uv`).
- Tests of one service: `docker compose run --rm --no-deps -e BIFLOW_MOCK=1 -e FAKE_LLM=1 <service> sh -c "pip install -q pytest && python -m pytest -q"`
  (from the service folder; see each `services/<module>/README.md`).
- Containers run Python 3.11: check syntax with Python 3.11 before committing.

```
contracts/            shared request/response models, service kit, LLM helper
config/models.yaml    LLM model names per profile (api | ollama | low_ram)
configs/              datasets/, marts/<domain>/, kpis/<domain>.yaml, recommendations/<domain>.yaml
services/<module>/    app/ · mock/ · eval/ · tests/ · Dockerfile · requirements.in / .lock
prompts/<module>/     versioned prompts (prompt library)
data/demo/            committed demo data (bike sharing); data/raw/ and data/runs/ are local only
tests/fixtures/       1% Olist sample (demo + tests), LLM fixtures
scripts/              start helpers, lock_all.py, make_sample.py, get_olist.py
docs/                 spec, rules, integration notes, results
```
