# profile_clean (BO3)

Profiler + cleaner on port **8103**. Modes: `profile`, `clean`.

## Setup

```powershell
cd services/profile_clean
python -m venv .venv
.venv\Scripts\pip install -e ..\..\contracts uvicorn pytest
.venv\Scripts\pip install -r requirements.in
```

## Run

```powershell
$env:DATA_DIR = "..\..\data"
$env:BIFLOW_MOCK = "0"
$env:FAKE_LLM = "1"
.venv\Scripts\uvicorn app.main:app --port 8103
```

Mock-only service (orchestrator stub):

```powershell
$env:BIFLOW_MOCK = "1"
.venv\Scripts\uvicorn mock.app.main:app --port 8103
```

## Tests

```powershell
$env:FAKE_LLM = "1"
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check app tests
```

## Eval / benchmarks

```powershell
$env:FAKE_LLM = "1"
.venv\Scripts\python eval\run_all.py --fast
```

Results: `eval/results/benchmark_table.md`, `eval/results/runs.jsonl`.

**Live LLM eval (optional):** set `FAKE_LLM=0`, configure `.env` (`LLM_PROVIDER`, `LLM_BASE_URL`), then:

```powershell
.venv\Scripts\python eval\bench_llm_advisory.py
```

## Docker

From repo root: `docker compose --profile core build profile_clean` (syntax validated; requires Docker).

## Playground (Streamlit dev UI, port 8503)

Start the service (8103), then the playground:

```powershell
$env:DATA_DIR = "..\..\data"
$env:BIFLOW_MOCK = "0"
$env:FAKE_LLM = "1"
.venv\Scripts\uvicorn app.main:app --port 8103

# another terminal:
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\streamlit run playground.py --server.port 8503 --server.headless true
```

Open http://localhost:8503 — use **Load demo data** if `data/runs/<run_id>/00_ingest/` is empty, then run Profile → Clean → Profile (after).

### Using your own CSV

1. Open the **My uploads** tab.
2. Upload one or more CSV/TSV/TXT files (optional size limit in the sidebar).
3. Review the **parse report** (encoding, delimiter, skipped lines, type inference) and adjust overrides if needed; click **Ingest to run folder**.
4. Review or edit the **draft dataset YAML** (Validate / Reset to generated); LLM advisory is **off by default** for uploads.
5. Click **Run everything** (Profile → Clean → Profile after) and inspect before/after cards, review queue, changed cells, and downloads (CSV, parquet, zip, logs).

**Privacy:** If `LLM_PROVIDER=api` (not local Ollama), enabling LLM in the YAML can send column names and sample values to a third-party API — the UI shows a warning and requires explicit consent before turning LLM on.

### Safety guarantees and column roles

Cleaning uses deterministic **column roles** (`id`, `categorical`, `binary_flag`, `discrete_count`, `continuous_numeric`, etc.) in generated YAML (`expected_schema.<table>.<col>.role`). The service applies a **type-safety guard** that blocks numeric imputation/outlier flagging on strings, ids, and categoricals even if the YAML requests it (entries go to `review_queue.json`). Original column dtypes are preserved; imputation is cast back to the source type; flags are boolean (`__imputed`, `__outlier`, `__high_null`). See `docs/bo3_fix_notes.md` and `tests/test_cross_dataset_safety.py`.

### How recognition works

Each column gets `role`, `semantic_type`, `confidence`, and `evidence` in `recognition_report.json` (profile and clean). Actions with confidence ≥ 0.9 (configurable in YAML) may auto-apply safe standardisation, sentinel→null, and case/accent category maps; everything else goes to the **review queue**. Approved mappings are stored in `data/decisions/<dataset_slug>.yaml` and merged on the next run.

### Supported inputs and issue types

Upload: CSV/TSV/TXT, Parquet, JSON/JSONL, Excel (first sheet). Detected issue classes include hidden sentinels, currency/percent strings, category variants, duplicates, whitespace/Unicode noise, and ambiguous dates (review, never silent guess).

### Eval

```powershell
.venv\Scripts\python eval\universal\make_torture_corpus.py
.venv\Scripts\python eval\universal\run_metrics.py   # full corpus report
make eval-universal   # alias if wired in Makefile; else command above
```

Fast pytest subset: `tests/test_universal_corpus_fast.py`.

## Endpoints

- `GET /health` — `llm: ok|unreachable|disabled`
- `GET /v1/meta` — modes, models, prompt versions, `lineage_steps`
- `POST /v1/run` — `mode=profile|clean`
- `POST /v1/eval` — fast benchmark subset
