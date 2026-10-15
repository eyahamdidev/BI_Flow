# BIFlow: Team Technical Spec (v2)

Multi-agent BI pipeline: automated, transparent, traceable.
Pilot dataset: Olist Brazilian E-Commerce (Kaggle, 9 CSV tables, ~100k orders, 2016–2018).
Local-first and open source. The LLM runs either **locally on Ollama** or through **any OpenAI-compatible API key**, chosen per developer in `.env`.

---

## 0. How to read this

Six business objectives (BOs), one owner each. Each BO owns one module (BO1 owns two things: the orchestrator and the ETL module).

| Owner | BO | Module | Port |
|---|---|---|---|
| BO1 | Reduce time-to-insight | **Orchestrator / gateway** (LangGraph, CLI, run manifest) + **ETL module** (DuckDB + dbt) | 8000 / 8101 |
| BO2 | Build trust (XAI) | **Auditor** (lineage graph, trace report, "Explain this KPI") | 8102 |
| BO3 | Cut manual cleaning | **Profiler + Cleaner** | 8103 |
| BO4 | Improve reliability | **Ingest + Validate + Quality score** (plus CI, tests, contracts tooling) | 8104 |
| BO5 | Scale across sectors | **Semantic & KPI** (KPI catalog, RAG, dataset onboarding) | 8105 |
| BO6 | Decide faster and better | **Analyst** (trends, anomalies, drivers, recommendations) + **Dashboard** (Streamlit) | 8106 / 8501 |

Modules talk only over HTTP + JSON through frozen contracts. Nobody imports anyone else's code. Section 1 holds the rules that prevent integration problems, section 2 the shared platform (including the Ollama-or-API choice), sections 3 to 8 one spec per owner, section 9 the common benchmark protocol, section 10 the deliverables checklist, section 11 open decisions and risks.

> The team list has 5 people for 6 BOs. Decide on day 1 who takes two. Suggested: BO1 + BO4 (both are runtime/engineering heavy, no ML tuning). If a sixth member joins, give them the Streamlit UI polish and the demo script, and keep BO6 on analysis.

Assumptions to confirm on day 1: (a) Python 3.11 everywhere; (b) every model name in section 2.4 still exists in Ollama's library or your API provider's catalog (catalogs change often: replace a missing name by its closest sibling and note it in the run log); (c) laptop RAM per person (decides local model size); (d) nothing in the pilot dataset is private (Olist is public), but any private dataset used later follows the privacy note in 2.4.

---

## 1. Anti-integration rules (non-negotiable)

1. **One container (or one folder with its own venv) per module, one `requirements.lock` per module.** No shared virtualenv. Heavy libraries (scikit-learn stacks, dbt, Streamlit, ChromaDB) live only in the module that needs them. Docker is optional for development (`make dev` runs every service with `uvicorn` in its own venv); `docker compose up` is the reference way to run the demo.
2. **Modules never call each other. Only the orchestrator calls modules.** If the Auditor needs the KPI definitions, the orchestrator passes the file reference. Cross-module runtime dependencies are zero.
3. **Contracts are frozen in week 1** (section 2.2) in a tiny `contracts/` package (JSON Schema + generated pydantic v2 models + a 60-line LLM helper). Only BO1 edits it; changes need a PR approved by all owners and a version bump. Each service pins `biflow-contracts==X.Y`.
4. **Mock first.** By end of week 1 every owner ships a mock service that returns fixture responses on the real endpoints. The orchestrator builds against mocks, then swaps the real service in by changing one URL in `.env`.
5. **Data travels by reference.** Stages write files under `data/runs/<run_id>/<stage>/` and requests carry `inputs: {name: path}`, never DataFrames or bytes. Paths are relative to the shared `DATA_DIR`.
6. **LLM calls go over plain HTTP (`httpx`) to an OpenAI-compatible endpoint, not through SDKs** (no SDK version drift). `LLM_BASE_URL`, `LLM_API_KEY` and model names come from `.env`. Ollama exposes the same format at `http://localhost:11434/v1`, so switching is a config change, not a code change (section 2.4). Retry with exponential backoff on HTTP 429 and 5xx.
7. **Code computes, the LLM explains.** Every number, join, KPI value, anomaly flag and cleaning action is produced by deterministic code or classical ML. The LLM receives computed facts and writes text, or picks from a **closed menu** returned as validated JSON. It never does arithmetic and never invents data. Every LLM output that is machine-read is validated with pydantic and retried (max 2) with the validation error as feedback.
8. **Every LLM-assisted step has a no-LLM fallback.** If the LLM is unreachable or its output fails validation twice, the module degrades (skip the optional step, log a warning, return `status: partial`), it does not crash.
9. **Models are chosen by config, not code.** `config/models.yaml` maps roles (`llm_main`, `llm_fast`, `embedder`) to model names per provider profile. Benchmark winners are written there at the end of week 4 (freeze).
10. **Every service exposes the same four endpoints (2.3), the same error format and the same timeout budget.**
11. **Contract tests run in CI** (pytest + jsonschema) against each module's mock and, when available, its real service. A red contract test blocks merge. CI never calls an LLM: it uses `FAKE_LLM=1`.
12. **Temperature 0 and fixed seeds for every benchmark run.** Every run is logged (module, provider, model, prompt version, variant, dataset version) to MLflow (local file backend).
13. **Integration session each Thursday from week 3.** Merge to `main` only on green contract tests.

---

## 2. Shared platform

### 2.1 Services

| Service | Port | Owner | Notes |
|---|---|---|---|
| gateway (FastAPI + LangGraph) | 8000 | BO1 | pipeline graph, CLI backend, `/api/*` for the dashboard |
| etl | 8101 | BO1 | DuckDB + dbt-core + dbt-duckdb |
| auditor | 8102 | BO2 | networkx, pyvis data, report writer |
| profile_clean | 8103 | BO3 | pandas, scikit-learn |
| ingest_quality | 8104 | BO4 | connectors, pandera, quality score |
| semantic_kpi | 8105 | BO5 | ChromaDB (persistent, inside this container only) |
| analyst | 8106 | BO6 | statsmodels, scipy, scikit-learn |
| dashboard (Streamlit) | 8501 | BO6 | read-only on run data, calls gateway `/api` for Explain |
| ollama | 11434 | BO1 (compose) | optional, only if the developer chooses local LLM or local embeddings |
| mlflow | 5000 | BO1 | optional (`ml` profile), local file store |

Compose profiles: `core` (all services), `ollama` (adds the Ollama container), `ml` (adds MLflow). Developers who run Ollama natively on their machine skip the `ollama` profile and point `LLM_BASE_URL` to it.

### 2.2 Contracts (frozen week 1)

**Request (gateway → module):** `request_id`, `run_id`, `dataset` (name), `mode` (module-specific, e.g. `profile`, `clean`), `config_ref` (path to dataset YAML), `inputs` (map name → path), `options` (object), `lang` (en, fr), `trace_parent`.

**Response (module → gateway):** `request_id`, `run_id`, `module`, `status` (`ok`, `partial`, `error`), `outputs[]` (Artifact), `metrics{}` (numbers about the work: rows in/out, nulls fixed, score, etc.), `warnings[]`, `lineage_events[]`, `llm_calls[]` (prompt_id@version, model, provider, tokens, ms, cache_hit), `latency_ms`, `error` (optional: `code`, `message`).

**Artifact:** `name`, `kind` (`parquet`, `csv`, `duckdb`, `json`, `html`, `md`, `png`), `path` (relative to `DATA_DIR`), `rows` (or null), `sha256`, `label`.

**LineageEvent** (modules return these; **only the gateway writes them** to `lineage/events.jsonl`, so there is no shared logger library and no write conflicts):
```json
{
  "event_id": "uuid", "run_id": "…", "ts": "ISO-8601",
  "agent": "profile_clean", "step": "impute_product_weight",
  "inputs":  [{"name": "products", "path": "…", "rows": 32951, "sha256": "…"}],
  "outputs": [{"name": "products", "path": "…", "rows": 32951, "sha256": "…"}],
  "rule": "knn_impute(product_weight_g, k=5)", "rows_affected": 2,
  "method": "deterministic | ml | llm_assisted",
  "params": {}, "llm": {"model": "…", "prompt_id": "…@v2", "response_sha256": "…"}
}
```

**KPI definition** (YAML, one file per domain in `configs/kpis/`; BO5 owns the schema):
```yaml
- id: revenue
  name: Revenue
  description: Total payments received for delivered orders.
  sql: "SELECT date_trunc('month', order_purchase_timestamp) AS period, SUM(payment_value) AS value FROM fact_orders WHERE order_status='delivered' GROUP BY 1"
  grain: month
  unit: BRL
  direction: higher_is_better
  dimensions: [product_category, customer_state, payment_type]
  synonyms: [sales, turnover]
  caveats: "Excludes cancelled/unavailable orders."
```

**Insight** (BO6 output, consumed by BO2 and the dashboard): `id`, `kpi_id`, `type` (`trend`, `anomaly`, `driver`, `recommendation`), `period`, `severity` (`info`, `review`, `high`), `facts{}` (the numbers), `narrative` (text), `rule_id` (or null), `source` (`rule`, `model`, `both`).

**Run manifest** (`run_manifest.json`, written by the gateway after every stage): `run_id`, git commit, package versions, config hash, **provider, model names, embedder name**, stage status and timings, warnings.

**Error codes:** `BAD_INPUT`, `SCHEMA_MISMATCH`, `UNSUPPORTED_SOURCE`, `MODEL_UNAVAILABLE`, `TIMEOUT`, `INTERNAL`.

### 2.3 Endpoints every module exposes

| Endpoint | Purpose |
|---|---|
| `GET /health` | process up, LLM reachable (if the module uses one) |
| `GET /v1/meta` | module name, contract version, modes supported, models in use, prompt versions |
| `POST /v1/run` | the module's main job (Request → Response), selected by `mode` |
| `POST /v1/eval` | runs the module's own labelled set and returns metrics (nightly job or on demand) |

**Timeout budgets:** ingest 60 s, profile 60 s, clean 120 s, etl 180 s, kpi 90 s, analyst 120 s, audit 120 s, explain 30 s, gateway full run 15 min. A module must degrade (`status: partial`), not crash.

### 2.4 LLM provider: Ollama **or** API key (each developer chooses)

Both options speak the same OpenAI-compatible protocol (`/v1/chat/completions`, `/v1/embeddings`), so **no code changes between them**. Each developer sets `LLM_PROVIDER` in their own `.env`.

```dotenv
# ---- choose ONE of the two blocks ----

# Option A: local with Ollama (free, private, needs RAM)
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama                      # any non-empty string

# Option B: any OpenAI-compatible API (Groq, OpenRouter, OpenAI, Together, Gemini-compat…)
# LLM_PROVIDER=api
# LLM_BASE_URL=https://api.groq.com/openai/v1
# LLM_API_KEY=sk-...                    # never commit this file

# model names come from config/models.yaml by profile; override per developer if needed
# LLM_MODEL_MAIN=
# LLM_MODEL_FAST=

# embeddings: ollama | api | local   (see below)
EMBED_PROVIDER=ollama
```

**`config/models.yaml`** (edited by BO1, benchmark winners at freeze):
```yaml
profiles:
  ollama:
    llm_main: qwen2.5:7b-instruct
    llm_fast: llama3.2:3b
    embedder: nomic-embed-text
  api:
    llm_main: llama-3.3-70b-versatile      # example on Groq; replace per provider
    llm_fast: llama-3.1-8b-instant
    embedder: null                         # most chat APIs have no embeddings; use ollama or local
  low_ram:                                 # 8 GB laptops, local
    llm_main: llama3.2:3b
    llm_fast: llama3.2:3b
    embedder: nomic-embed-text
embedder_options:
  ollama: nomic-embed-text                 # or bge-m3
  local: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2   # in-container, no Ollama needed
  api: text-embedding-3-small              # only if the provider has /v1/embeddings
```

**Rules for the choice**
1. **Same code path.** The shared helper `contracts/biflow_llm.py` reads `.env` + `models.yaml` and exposes `chat_text()`, `chat_json(schema)`, `embed()`. Nobody writes their own client.
2. **Structured output with a fallback ladder:** try `response_format` JSON schema → if the provider rejects it, try JSON mode → if that fails, prompt "return only JSON" and parse. Every result is validated by pydantic regardless. This is what makes small local models and different APIs interchangeable.
3. **Cache.** Responses are cached in a local SQLite file keyed by hash of (provider, model, prompt id@version, rendered prompt, parameters). Re-running a benchmark or a pipeline on unchanged data spends nothing.
4. **Rate limits (API mode):** backoff honouring `Retry-After`; one key per developer for experiments, one separate key for the demo and nightly eval; benchmarks run one at a time per key; tokens used and 429 count are logged.
5. **Embeddings are the one thing the team must agree on.** The KPI index is built with one embedder; a different embedder makes vectors incomparable. The Chroma collection stores `embedder_name` in its metadata; on mismatch the semantic module **rebuilds the index automatically** (it is tiny: tens of KPI entries). So developers can differ in LLM choice but each machine rebuilds its own index when the embedder differs. Default is Ollama `nomic-embed-text`; `local` (sentence-transformers inside the BO5 container) is the no-Ollama option.
6. **CI uses `FAKE_LLM=1`**: a deterministic fake that returns canned JSON/text from `tests/fixtures/llm/`. No Ollama, no key, no network.
7. **Reproducibility note for the report:** results can differ slightly between providers and models. That is expected; the run manifest records provider and model, and the numbers (KPIs, quality scores) never depend on the LLM. Only narrative text and optional suggestions do.
8. **Hardware guide.** 16 GB RAM: `qwen2.5:7b-instruct` (Q4) is comfortable. 8 GB RAM: use the `low_ram` profile or use API mode. CPU-only works, at roughly 5–15 tokens/s; the LLM budget in 2.7 keeps a full run usable.
9. **Privacy.** Olist is public, so API mode is fine for the pilot. For any private dataset, use Ollama, or mask names, ids and free text before the call and document the decision in the report. State the choice explicitly either way.

**Model candidates by role (confirm names on day 1):**

| Role | Local (Ollama) | API (examples) |
|---|---|---|
| Main LLM (narrative, reports) | `qwen2.5:7b-instruct`, `llama3.1:8b`, `qwen3:8b` | `llama-3.3-70b-versatile`, `qwen/qwen3-32b`, `openai/gpt-oss-120b` (Groq names) or equivalents on other providers |
| Fast LLM (closed-menu choices, JSON) | `llama3.2:3b`, `qwen2.5:3b-instruct` | `llama-3.1-8b-instant`, `openai/gpt-oss-20b` |
| Embedder | `nomic-embed-text`, `bge-m3` | provider's `/v1/embeddings` if present |
| Embedder (no Ollama) | `paraphrase-multilingual-MiniLM-L12-v2` in-container | n/a |

### 2.5 Repo layout

```
biflow/
  contracts/                 BO1 (JSON Schema + pydantic + biflow_llm.py + FakeLLM)
  config/models.yaml         BO1, edited at freeze
  configs/
    datasets/olist.yaml      schema, relationships, cleaning rules, KPI file ref
    kpis/ecommerce.yaml      BO5
    recommendations/*.yaml   BO6 (pattern → action templates)
  services/
    gateway/                 BO1   (LangGraph, CLI, /api)
    etl/                     BO1   (+ dbt_project/)
    auditor/                 BO2
    profile_clean/           BO3
    ingest_quality/          BO4
    semantic_kpi/            BO5
    analyst/                 BO6
    dashboard/               BO6   (Streamlit)
      each: Dockerfile, requirements.lock, app/, mock/, tests/, prompts/, eval/
  prompts/_template.yaml
  data/{raw,runs,uploads}/   gitignored
  tests/{contract,smoke,fixtures}/
  .github/workflows/ci.yml   BO4
  docker-compose.yml         profiles: core, ollama, ml
  Makefile                   dev, up, test, eval
  CODEOWNERS
  README.md
```

**Git workflow:** `main` protected; PR required; CI green; one review. Branches `bo1/<topic>` … `bo6/<topic>`. `CODEOWNERS` maps each service folder to its BO owner; `contracts/` and `config/models.yaml` require everyone. Conventional commits (`feat(bo3): add knn imputer`). Contract changes start with an issue and bump `CONTRACT_VERSION`.

### 2.6 Prompt library format (one file per prompt version, same for everyone)

`prompts/<module>/<prompt_id>/v<N>.yaml` with fields: `id`, `version`, `owner`, `role_in_system`, `technique` (few-shot, structured output, role prompting, closed menu, guardrails), `model_role` (`llm_main` or `llm_fast`), `text`, `output_schema`, `failure_cases_observed`, `fix_applied`, `metric_before`, `metric_after`, `date`. For each key prompt keep v1 and at least one later version with the before/after metric. The prompt registry check script (BO1) fails CI if a prompt used in code has no file.

### 2.7 LLM call budget per full Olist run (keeps local runs usable)

| Where | Calls | Mode |
|---|---|---|
| Cleaning suggestions (BO3) | 0–10 | closed-menu JSON, T=0 |
| KPI shortlist selection (BO5) | 0 on repeat runs (cached) | closed-menu JSON, T=0 |
| Insight narratives (BO6) | 10–20 | text, T=0.3 |
| Audit report sections (BO2) | ~8 | text, T=0.2 |
| Explain this KPI (BO2) | on demand | text, T=0.2 |
| Run summary (BO1) | 1 | text, T=0.2 |

---

## 3. BO1: Reduce time-to-insight (Orchestrator + ETL)

**Mission.** One command takes raw files to a live dashboard with no manual step, and the time saved is measured against a documented manual baseline.

**Stack.** Python 3.11, FastAPI, LangGraph, pydantic, httpx, DuckDB, dbt-core, dbt-duckdb, pandas/pyarrow, MLflow (file backend), Docker Compose, Typer (CLI).

**Approach.**
1. **Week 1 (platform):** write and freeze `contracts/`, `config/models.yaml`, the Compose file, repo skeleton, mock template, prompt template, `biflow_llm.py` with `FakeLLM`; publish a one-page "how to add your service" guide.
2. **Gateway and graph:** nodes `ingest → profile → score_before → clean → validate → score_after → etl → kpi → analyst → dashboard_config → audit`. Sequential. Per-node timeout. On failure: retry up to 2 times, then mark the stage `failed`, **skip to the Auditor** so the failure is still explained, and finish with a partial run. State persisted to `run_manifest.json` after every node; `biflow run --resume <run_id>` continues at the first non-`ok` stage.
3. **Lineage writer:** the gateway appends every module's `lineage_events[]` to `lineage/events.jsonl` and fills the `inputs/outputs` hashes it can verify itself (it recomputes the SHA-256 of declared artifacts).
4. **ETL module (dbt on DuckDB):** loads cleaned parquet into `biflow.duckdb`, runs dbt.
   - Staging: `stg_orders`, `stg_order_items`, `stg_payments`, `stg_reviews`, `stg_customers`, `stg_products`, `stg_sellers`, `stg_geolocation`.
   - Marts: `fact_orders` (one row per order: totals, delivery days, delay vs estimate, review score, main payment type), `fact_order_items`, `dim_customer`, `dim_product` (English category), `dim_seller`, `dim_date`.
   - dbt tests: unique + not_null on keys, relationships fact → dim.
   - **Join generation:** staging and join SQL are rendered from a Jinja template driven by the dataset YAML (`relationships:` block). The YAML is the one place to edit per dataset. The LLM does not write SQL.
5. **CLI:** `biflow run --dataset olist`, `biflow dashboard --run latest`, `biflow eval --all`.
6. **Benchmark harness:** per-stage wall time into the manifest, plus a written manual baseline (how long the same prep takes by hand) so "time-to-insight reduced" is a number in the report.
7. **Evaluation harness:** one command runs every module's `/v1/eval` and the end-to-end test, renders one results table (the final results page of the report).

**Models to benchmark (provider and model choice for the whole system).**

| Role | Candidate | Why |
|---|---|---|
| Main LLM, local | `qwen2.5:7b-instruct` | default local candidate |
| Main LLM, local | `llama3.1:8b`, `qwen3:8b` | alternatives of the same size |
| Main LLM, local (low RAM) | `llama3.2:3b` | does a small model suffice when numbers are pre-computed? |
| Main LLM, API | a 70B-class model | quality upper bound |
| Fast LLM, API | an 8B-instant / 20B-class model | cheap and fast |
| Setup | local-only vs API-only vs hybrid (local embedder + API LLM) | measures quality, latency, cost, rate limits |

**Experiments:** (a) full run time with vs without the LLM steps (shows the LLM is not on the critical path for numbers); (b) cold vs cached LLM run; (c) cost of `--resume` vs full rerun.

**Metrics.** End-to-end run time (p50/p95 over 5 runs), time per stage, dbt test pass rate, row-reconciliation checks, contract-test pass rate, manual-vs-automated time ratio, system-wide LLM failure fallback rate.

**Deliverables.**
- gateway with LangGraph graph, CLI, `/api/*` for the dashboard, `--resume`
- etl service (`/v1/run`), dbt project, mock, tests, Dockerfile, lockfile
- `contracts/`, `config/models.yaml`, mocks for every module, CI contract tests (with BO4)
- Compose file with profiles, README with run instructions
- evaluation harness and results table, merged prompt library and registry check
- Report section (about 1.5 pages): architecture, why a fixed pipeline graph instead of a free agent swarm (auditable, testable, bounded latency), manual-baseline comparison

**Integration notes.** BO1 is the only caller of other modules. It owns the "stage → module → mode" table in `gateway/graph.yaml`. Acceptance: full Olist run under 10 minutes on a 16 GB laptop (excluding model download); dbt tests pass; orders in `fact_orders` reconcile with distinct orders in staging.

---

## 4. BO2: Build trust (Auditor, lineage, XAI)

**Mission.** Anyone (Sara, Amine, Karim) can see what happened to the data and why a KPI says what it says. Wording is plain language; claims are always tied to logged facts.

**Stack.** Python 3.11, FastAPI, networkx, pyvis (graph data for Streamlit), jinja2, pydantic, httpx to the LLM endpoint.

**Approach.**
1. **Lineage graph builder** (`mode: graph`): reads `lineage/events.jsonl` and builds a graph (datasets/KPIs/insights as nodes, transformations as edges). Output `lineage_graph.json` (nodes, edges, per-node metadata). Query helper: `upstream(kpi_id)` returns the path raw table → cleaning rules → dbt models → KPI SQL.
2. **Trace report** (`mode: audit`): for each stage, a structured table first (what ran, rows in/out, rules applied, counts, method type deterministic/ml/llm_assisted, duration, warnings); for each KPI, definition + SQL + source tables + cleaning steps touching them; for each insight, the facts it came from. Output `trace_report.json` and `trace_report.md`.
3. **Prose layer:** the LLM turns one structured section at a time into readable text from a fact sheet (never from raw logs). A **fact-check pass** (regex + code, no model) extracts every number in the prose and verifies it appears in the section's fact sheet; mismatch → regenerate (max 2) → if still wrong, fall back to the template text with no LLM prose and set `warnings`.
4. **Explain this KPI** (`mode: explain`, invoked via gateway `/api/explain`): input `kpi_id`, `period`, optional `compare_to`. The gateway first gathers (a) KPI definition from BO5's output, (b) the lineage path from BO2's graph, (c) the driver decomposition from BO6's `drivers.json`, and passes the file refs. BO2 builds a **fact sheet**, the LLM writes 3–5 sentences using only the fact sheet, then the fact-check pass runs. Abstains ("not enough logged information") if the fact sheet is empty.
5. **Completeness test:** a check that every step name registered by the other modules in their `/v1/meta` (`lineage_steps`) has at least one event in the run. Missing steps are listed in the report as "untracked transformations".

**Models to benchmark.**

| Role | Candidate | Why |
|---|---|---|
| Prose writer | template-only (no LLM) | baseline: readable but dry |
| Prose writer | local `qwen2.5:7b-instruct`, `llama3.1:8b`, `llama3.2:3b` | local candidates |
| Prose writer | API 70B-class / 20B-class | quality upper bound / cheap |
| Fact-check | regex + number parser (default) | cheap, deterministic |
| Fact-check (optional) | LLM judge with a **different** model than the writer | catches wording distortions that numbers miss |
| Prompting | plain instruction vs few-shot vs "fact-sheet only" guardrail | measures hallucination reduction |

**Metrics.** Lineage coverage (% of registered steps with events, target 100%), fact-check first-try pass rate (target at least 95%), unsupported-statement rate (target 0 after fallback), faithfulness on 20 hand-labelled explain answers (each claim supported or not), readability check by 5 non-technical reviewers (1–5 clarity score), p50/p95 latency.

**Datasets.** A set of 20 (kpi, period) explain cases with expected driver lists (built with BO6); 3 planted "bad prose" examples to test the fact-checker.

**Deliverables.**
- auditor service with `/v1/run` (modes `graph`, `audit`, `explain`), mock, tests, Dockerfile, lockfile
- lineage graph JSON schema and the Streamlit-ready node/edge format (agreed with BO6)
- prompt library `prompts/auditor/` with before/after
- Report section (about 1.5 pages): traceability design, fact-check mechanism, results

**Integration notes.** Never writes to `events.jsonl` (gateway does). Never reads raw tables; it only reads logs, definitions, and BO6's facts. Statements about the data always come from a fact sheet.

---

## 5. BO3: Cut manual cleaning (Profiler + Cleaner)

**Mission.** Detect and fix data problems automatically, with every fix logged, justified and reversible, and with a human-review queue for anything uncertain.

**Stack.** Python 3.11, FastAPI, pandas, pyarrow, numpy, scikit-learn, scipy, pyyaml, pydantic, httpx to the LLM endpoint. Optional `ydata-profiling` (with `minimal=True`) for an HTML report.

**Approach.**
1. **Profiler** (`mode: profile`): per column dtype, null %, distinct count, min/max, mean/std, top values, IQR outlier counts, pattern checks (zip, ids, dates); per table duplicate rows/keys and date parseability; cross-table FK orphan rates. Output `profile.json` (machine-readable, consumed by the cleaner), optional `profile.html`. Runs again on the cleaned output (`mode: profile`, `options.stage=after`) to produce the before/after diff.
2. **Cleaner, rule layer** (`mode: clean`, YAML-driven by `cleaning_rules` in the dataset config): parse dates, trim/standardise strings, drop exact duplicates, dedupe `geolocation` by zip prefix (mean lat/lng), flag impossible values (negative price, delivery before purchase), fill English category names from the translation table, fix the known unmatched categories via a YAML mapping, per-column null strategy (`drop`, `constant`, `median`, `mode`, `flag_only`).
3. **Cleaner, ML layer:** numeric imputation (median, KNN, IterativeImputer) only where YAML permits; outlier detection with IQR, MAD, LOF or IsolationForest on selected numeric features (price, freight, weight); outliers are **flagged**, not deleted, unless a rule says so.
4. **Cleaner, LLM layer (advisory, optional):** for issues the rules do not cover, the model receives a compact profile snippet and returns JSON from a closed menu (`drop_column | impute_median | impute_mode | flag | ignore`) plus a one-line reason. Validated by pydantic. Applied automatically **only** if the suggestion is inside the YAML's allowed actions for that column; otherwise written to `review_queue.json` ("needs human review").
5. **Outputs:** cleaned parquet per table, `quality_log.json` (every fix: rule, column, rows affected, before/after sample), `review_queue.json`, lineage events for every action. **Row reconciliation:** `in − dropped = out` for every table; every dropped row id is logged.
6. Olist-specific cases to handle: missing delivery dates for undelivered orders (keep, flag), missing English category names, geolocation duplicates, null review comments, products with missing dimensions.

**Models to benchmark.**

| Task | Candidate | Why |
|---|---|---|
| Numeric imputation | median / mode (baseline) | simplest |
| Numeric imputation | `KNNImputer`, `IterativeImputer` | does ML beat the baseline? (masked-value test) |
| Outlier detection | IQR, MAD (baseline) | transparent rules |
| Outlier detection | `IsolationForest`, `LocalOutlierFactor` | multivariate |
| Advisory LLM | rules-only vs rules + LLM suggestions | does the LLM add useful, safe suggestions? |
| Advisory LLM model | local 3B / 7B / 8B vs API 8B / 70B | smallest model that stays valid and safe |

**Metrics.** Imputation RMSE/MAE on artificially masked values (mask 10% of known values, compare), outlier precision/recall on injected anomalies (inject ~1% spikes into a copy), null-rate and duplicate-count reduction (before/after table), **silent-deletion count (target 0)**, row reconciliation pass rate (target 100%), LLM suggestion validity rate and "unsafe suggestion" count (target 0 auto-applied), p50/p95 latency.

**Datasets.** Olist tables; a corrupted copy with injected nulls, duplicates, and impossible values (generator script in `eval/`) with known ground truth.

**Deliverables.**
- profile_clean service (`/v1/run` modes `profile`, `clean`), mock, tests, Dockerfile, lockfile
- `cleaning_rules` block in `configs/datasets/olist.yaml`, well commented
- corruption generator and benchmark table (imputers, outlier methods, LLM on/off)
- prompt library `prompts/profile_clean/` with before/after
- Report section (about 2 pages): profiling, rule/ML/LLM layering, why advisory LLM, results

**Integration notes.** Reads only `data/runs/<id>/00_ingest/` parquet and the dataset YAML. Returns the quality log as an artifact and lineage events per action. Works on a second dataset with only YAML changes (BO5 provides the second dataset).

---

## 6. BO4: Improve reliability (Ingest, Validate, Quality score, CI)

**Mission.** The pipeline behaves predictably. Bad input is caught early and explained, results are reproducible, and a numeric score says how much to trust the data.

**Stack.** Python 3.11, FastAPI, pandas, pyarrow, pandera, SQLAlchemy (SQLite/DuckDB for the SQL demo), httpx, a tiny FastAPI mock API server for the API connector demo, pytest, jsonschema, ruff, pre-commit, GitHub Actions.

**Approach.**
1. **Ingestion** (`mode: ingest`): a `Connector` interface with three implementations, all returning `{table_name: DataFrame}` written to `data/runs/<id>/00_ingest/*.parquet` with a manifest (source, timestamp, sha256, row counts).
   - `CSVConnector` (Olist),
   - `SQLConnector` (SQLite/DuckDB file for the demo, SQLAlchemy URL in config),
   - `APIConnector` (paginated JSON, demoed against a local mock server).
   The connector is selected in the dataset YAML (`source: {type: csv|sql|api, …}`).
2. **Schema validation** (`mode: validate`): pandera schemas generated from `expected_schema` in the dataset YAML. Runs as an input contract on ingest output and an output contract on cleaned data. A mismatch returns `SCHEMA_MISMATCH` with a readable message (table, column, expected, found) instead of crashing six stages later.
3. **Data Quality Score** (`mode: score`): 0–100 per table and overall, deterministic, from five dimensions with weights in YAML: completeness, uniqueness, validity, consistency (FK integrity), timeliness. The orchestrator calls it before cleaning and after cleaning → visible improvement. Output `quality_score.json`.
4. **Reproducibility:** fixed seeds and a test that two runs on the same input and config give identical KPI values (hash compare). The manifest records git commit, package versions, config hash, provider and model.
5. **Test suite and CI:**
   - unit tests per service on tiny fixtures (`tests/fixtures/`, about 100 rows per table),
   - **contract tests** for every service's mock and real endpoints,
   - a **smoke test** of the full pipeline on a 1% sample with `FAKE_LLM=1` (target under 2 minutes, no Ollama, no key),
   - GitHub Actions: `ruff` + `pytest` on every PR; the registry check for prompts; the lockfile check.
6. **Resilience helpers** (documented patterns, not shared code): retry with backoff, timeouts on LLM calls, graceful skip when the LLM is down.

**Models to benchmark.** This BO is mostly engineering; the comparisons are about method, not models.

| Task | Candidate | Why |
|---|---|---|
| Score weights | equal weights vs expert weights | does the score track real defects? |
| Validation | pandera schemas vs custom rule checks | maintainability vs power |
| Anomalous-table detection | z-score on score dimensions vs IsolationForest across tables | optional extra signal |

**Metrics.** Score sensitivity (inject defects of known size; score must drop monotonically, report correlation), score before/after on Olist and on the corrupted copy, schema-error detection rate on 20 corrupted inputs (missing column, wrong type, extra column) with message-readability check, reproducibility (identical hashes), CI time, smoke-test time, contract-test pass rate.

**Deliverables.**
- ingest_quality service (`/v1/run` modes `ingest`, `validate`, `score`), mock, tests, Dockerfile, lockfile
- three connectors with demos (CSV, SQL, API mock server)
- CI workflow, contract-test suite, smoke test, fixtures, pre-commit config
- prompt library: none (no LLM), but the registry check script's CI hook
- Report section (about 1.5 pages): reliability design, score definition, test strategy, results

**Integration notes.** BO4 owns `.github/workflows/`, `tests/contract/` and fixtures, in coordination with BO1. Acceptance: same pipeline runs from CSV, SQL and API sources with only a config change; CI passes on every merge to `main`; corrupted input gives a readable failure and a log entry.

---

## 7. BO5: Scale across sectors (Semantic & KPI)

**Mission.** Moving to a new domain means adding config files, not rewriting agents. Compute KPIs deterministically and use RAG to map questions and new columns onto a KPI knowledge base.

**Stack.** Python 3.11, FastAPI, DuckDB (read), pandas, pyyaml, pydantic, ChromaDB (persistent, inside this container only), embeddings via the shared `embed()` helper (Ollama `nomic-embed-text` by default, or `local` sentence-transformers), httpx to the LLM endpoint.

**Approach.**
1. **Dataset config and KPI catalog:** `configs/datasets/<name>.yaml` (tables, schema, relationships, cleaning rules, KPI file, dimension names) and `configs/kpis/<domain>.yaml`. Services contain no Olist-specific code.
2. **Olist KPIs:** Revenue, Orders, Average order value, Average delivery time, Delivery delay vs estimate, Late-delivery rate, Payment mix, Average installments, Average review score, Low-review rate (score ≤ 2), Repeat-purchase rate and churn.
   > Churn note: most Olist customers buy once. Define churn as "no repeat purchase within 180 days of first order", report it as a cohort metric, and say so on the dashboard.
3. **KPI computation** (`mode: compute`): executes each catalog `sql` on `biflow.duckdb`, writes `kpi_values.parquet` (`kpi_id, period, dimension, dimension_value, value`) at month grain plus each KPI's declared dimension cuts. Writes `kpi_definitions.json` (metadata used by BO2, BO6 and the dashboard). Every query is emitted as a lineage event with its SQL.
4. **RAG knowledge base** (`mode: index`): each KPI entry (name, description, synonyms, formula, caveats) is embedded into a Chroma collection `kpi__<domain>` whose metadata stores the `embedder_name`; on mismatch it is rebuilt automatically.
5. **Question → KPI mapping** (`mode: map_question`): retrieve top-k, then (optionally) the LLM picks one id from the shortlist as validated JSON; fallback to the top-1 retrieval if the LLM is off. Used by the dashboard's Explain box ("sales last quarter" → `revenue`).
6. **New-dataset onboarding** (`mode: suggest_kpis`): given a table schema (names, types, sample values), retrieve similar KPI definitions, LLM proposes column bindings from the shortlist as JSON, the module renders a **draft YAML**. A human reviews it. It is never auto-executed.
7. **Second dataset:** onboard a differently shaped dataset (suggest an open HR attrition, bike-share or ride dataset) by writing YAML only. That is the evidence for "scale across sectors".

**Models to benchmark.**

| Role | Candidate | Why |
|---|---|---|
| Embedder (local, Ollama) | `nomic-embed-text` | default, small |
| Embedder (local, Ollama) | `bge-m3` | multilingual, larger |
| Embedder (in-container) | `paraphrase-multilingual-MiniLM-L12-v2` | no Ollama dependency |
| Retrieval | dense-only vs BM25-only vs hybrid | catalog is tiny; does hybrid help synonyms/typos? |
| KPI selection | retrieval top-1 only (baseline) | no tokens |
| KPI selection | + LLM pick from shortlist (local 3B/7B, API 8B/70B) | measures what the LLM adds |
| Onboarding | LLM column-binding vs rule-based name matching | accuracy of the draft YAML |

**Metrics.** KPI value correctness against manual pandas calculations (tolerance 0.1%), Recall@3 and MRR on a hand-made list of about 30 question→KPI pairs (include synonyms and typos), column-binding accuracy on the second dataset (draft YAML vs hand-written), index rebuild time, zero Python changes under `services/` for the second dataset, p50/p95 latency.

**Datasets.** `eval/datasets/kpi_questions.jsonl` (30+ pairs), second dataset plus its hand-written reference YAML.

**Deliverables.**
- semantic_kpi service (`/v1/run` modes `compute`, `index`, `map_question`, `suggest_kpis`), mock, tests, Dockerfile, lockfile
- `configs/kpis/ecommerce.yaml` and the second domain's YAML
- retrieval benchmark table (embedders, dense/BM25/hybrid, LLM on/off)
- prompt library `prompts/semantic_kpi/` with before/after
- Report section (about 2 pages): RAG corpus choice (KPI definitions), embeddings, vector store, retrieval evaluation, portability result

**Integration notes.** Only BO5 reads or writes `kpi__*` collections. Reads `biflow.duckdb` (read-only). Other modules get KPI information only through `kpi_definitions.json`.

---

## 8. BO6: Decide faster and better (Analyst + Dashboard)

**Mission.** Turn KPIs into insights and recommended actions a manager can use in the meeting, and show them in a dashboard generated from config.

**Stack.** Python 3.11, FastAPI, pandas, numpy, scipy, statsmodels, scikit-learn, pyyaml, pydantic, httpx to the LLM endpoint; Streamlit + Plotly for the dashboard; `pyvis` HTML embed for the lineage view (graph JSON from BO2).

**Approach.**
1. **Trend detection** (`mode: analyse`): per KPI series, linear regression slope with p-value (scipy), STL decomposition (statsmodels) for seasonality; output direction and strength.
2. **Anomaly detection:** robust z-score (median/MAD) per KPI series as baseline; STL-residual z-score and `IsolationForest` on multi-KPI monthly vectors as alternatives; each anomaly has KPI, period, expected vs actual, severity.
3. **Driver decomposition ("why did it move?")**: for a KPI delta between two periods, split the change across a declared dimension (category, state, payment type): ranked contributions `Δ_i = value_i,t − value_i,t−1` that **sum to the total delta**; for ratio KPIs, a mix vs rate decomposition. Output `drivers.json`, consumed by BO2's Explain.
4. **Recommendations:** a **rule table** in YAML maps patterns to action templates (e.g. `late_rate up AND top driver is region → "Review carrier performance for {states}"`). The LLM only rewrites the matched template into plain language tied to the numbers; it cannot add an action that is not in the rule table.
5. **Insights output:** `insights.json` as defined in 2.2.
6. **Dashboard generator** (`mode: dashboard_config`): produces `dashboard_config.json` from `kpi_definitions.json` and `insights.json`: one tile per KPI (value, delta vs previous period, sparkline), a trend chart with anomaly markers, breakdown charts per declared dimension.
7. **Streamlit app** (config-driven; no dataset-specific code): tabs **Overview**, **KPI explorer**, **Insights and actions**, **Data quality** (BO4 score before/after), **Lineage** (BO2 graph), **Explain** (calls gateway `/api/explain`). Filters: date range, category, state. Every chart shows a data-source label. A new dataset yields a working dashboard with no code edits.

**Models to benchmark.**

| Task | Candidate | Why |
|---|---|---|
| Anomaly detection | robust z-score (MAD), baseline | simple, transparent |
| Anomaly detection | STL residual z-score, `IsolationForest` | seasonality-aware / multivariate |
| Trend | linear slope vs Mann-Kendall (pymannkendall) | robustness to non-normal series |
| Narrative | template-only (baseline) | no LLM |
| Narrative model | local 3B/7B/8B vs API 8B/70B | faithfulness vs cost |
| Prompting | plain vs facts-only guardrail + number fact-check | hallucinated-figure rate |
| Recommendations | rule table only vs rule table + LLM rewrite | clarity gain without unsafe additions |

**Metrics.** Anomaly recall/precision on planted spikes (inject 20 known anomalies into copies of the KPI series; target recall at least 90%), driver decomposition sums to the delta (unit test, tolerance 1e-6), narrative faithfulness (every number appears in the facts; target 100% after fallback), recommendation traceability (100% carry a `rule_id`), dashboard load time (under 5 s from precomputed outputs), p50/p95 latency of `analyse`, clarity rating by 5 reviewers.

**Datasets.** KPI series from Olist; synthetic series with planted trend/seasonality/anomalies (generator in `eval/`); 15 hand-checked driver cases.

**Deliverables.**
- analyst service (`/v1/run` modes `analyse`, `dashboard_config`), mock, tests, Dockerfile, lockfile
- `configs/recommendations/*.yaml` rule table
- Streamlit dashboard with the six tabs, runnable with `biflow dashboard --run latest`
- anomaly and narrative benchmark tables
- prompt library `prompts/analyst/` with before/after
- Report section (about 2 pages): analysis methods, driver decomposition, recommendation guardrails, UI

**Integration notes.** Reads `kpi_values.parquet` and `kpi_definitions.json` only. Does not call the auditor; the Explain tab calls the gateway. The dashboard is a client of the gateway, not a module.

---

## 9. Common benchmark protocol

1. Fix the dataset version and the metric list before running anything.
2. **Baseline first** (the simplest option listed in each table), then each candidate. Temperature 0, same prompts, same seeds.
3. Log to MLflow: module, provider (ollama/api), model tag, prompt id and version, method variant, dataset version, quality metrics, p50/p95 latency, tokens used (API) or tokens/second (local), 429 count, peak RAM or VRAM (local only).
4. **Decision rule:** pick the best quality; if two are within noise, pick the smaller, faster, cheaper. Anything that fails a safety metric (silent deletions, unflagged invented figures, unsupported statements, numbers not in the fact sheet) is out regardless of speed.
5. **Local vs API comparison (system-level):** BO1 runs the same fixed task set (cleaning suggestions, KPI selection, narratives, explain answers) on the best local model and the best API model, then reports quality, latency, cost, and failure rate. The point is evidence for the "use whichever you see fit" choice, not a winner for everyone.
6. Report failed attempts with the reason. Honesty about what did not work is part of the grade.
7. **Freeze on Friday of week 4:** winners written to `config/models.yaml`; no new model after that.

---

## 10. Deliverables checklist

| Requirement | Where it is covered | Owner |
|---|---|---|
| Design Thinking documentation (deck) | `BIFlow_Presentation.html` | all |
| Working end-to-end pipeline on the pilot dataset | gateway + all modules, `biflow run` | BO1 (all contribute) |
| Business objectives mapped to measurable results | one metrics table per BO, merged by BO1 | each BO |
| Transparency and traceability demonstrated | lineage graph + trace report + Explain tab | BO2, BO6 |
| Data cleaning evidence (before/after) | quality log, quality score, profile diff | BO3, BO4 |
| Scalability proof (second dataset, config-only) | second dataset run | BO5 |
| Insights and recommendations | analyst + dashboard | BO6 |
| Model/method benchmark tables with failed attempts | section 9 protocol, MLflow | each BO |
| Prompt library with before/after | `prompts/<module>/`, merged export | all, merged by BO1 |
| Ollama-or-API support shown | `.env` switch, local-vs-API comparison | BO1 |
| Run instructions | repo README, Compose, Makefile | BO1 |
| Technical report | each owner writes 1.5–2 pages, BO1 merges | all |
| Demo | everyone speaks, everyone can answer on any module | all |

---

## 11. Open decisions and risks

**To confirm on day 1**
1. BO-to-person assignment (5 people, 6 BOs).
2. Laptop RAM per person: decides who uses Ollama local, who uses an API key.
3. Which API provider(s) the team will use for API mode (any OpenAI-compatible one).
4. Second dataset for BO5/BO3.
5. Docker for everyone, or venv-per-service for development with Docker only for the demo.
6. Report length and delivery date.

**Risks**

| Risk | Mitigation |
|---|---|
| Small local LLM returns invalid JSON or weak prose | pydantic validation with retry, closed menus, fact-check pass, no-LLM fallbacks, response cache |
| Local LLM too slow on some laptops | tiny LLM budget (2.7), `low_ram` profile, API mode as the alternative |
| API rate limits or outage during the demo | prompt cache, local fallback profile, demo run pre-cached |
| Developers use different providers → different narrative text | numbers never depend on the LLM; manifest records provider/model; benchmark uses a fixed provider per run |
| Embedder differs between machines | index stores `embedder_name` and rebuilds automatically; default is the same for everyone |
| Contracts drift between modules | frozen contracts, fixtures, contract tests in CI |
| Scope creep per BO | acceptance criteria and metrics above are the definition of done; anything else is stretch |
| dbt learning curve | BO1 owns dbt; others read marts via DuckDB |
