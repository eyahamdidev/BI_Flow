# Integration notes (BO1, branch `bo1/foundation`)

What happened when each module was merged and run inside the real pipeline (Docker, real Olist data).
**Fixed** = already changed in `bo1/foundation` (please pull before continuing). **Owner** = still yours to decide or fix.

## Platform changes everyone should know

- **Containers mirror the repo layout:** data is mounted at `/srv/data` and `DATA_DIR=/srv/data`, so paths in YAML
  (`data/raw/olist`, `configs/marts/...`) mean the same locally and in Docker. Find the repo root by searching upward
  for `configs/datasets` (never a fixed `parents[N]`: it points at `/` inside the container).
- **Per-module mock switch:** `BIFLOW_MOCK_<MODULE>=0` makes one module real while the others stay mocked.
- **Lockfiles:** `python scripts/lock_all.py <service>` (uv, Linux / Python 3.11). Do not commit `pip freeze` output
  (Windows-only packages, `-e ../../contracts` paths break the Docker build).
- **Frozen config per run:** the gateway resolves `extends:` and writes `data/runs/<id>/dataset.yaml`; `config_ref`
  points to it. `configs/datasets/olist_sample.yaml` = Olist with the committed 1% sample.
- **Python 3.11 in containers:** check with `py -3.11 -m py_compile ...` (3.12+ syntax such as backslashes in
  f-string expressions breaks the image).
- **The gateway checks outputs:** a real module that answers `ok` but whose declared output files do not exist is
  marked failed.
- **LLM calls are bounded:** `LLM_TIMEOUT_S` (30) and `LLM_RETRIES` (3) per call in the shared helper; stages that
  call the LLM many times also have a total budget and fall back to templates (never miss the stage budget).
- **Docker networking:** if `docker info` shows an HTTP proxy, containers need `HTTPS_PROXY` (see `.env.example`).
- **Dev loop:** `docker-compose.override.yml` mounts code: `docker compose restart <service>` after a change.
- **Groq models:** the Llama models are gone from Groq; `config/models.yaml` api profile = `openai/gpt-oss-120b` /
  `openai/gpt-oss-20b`.

## BO2 Auditor

- Fixed: branch had an unrelated git history; re-parented onto the team's initial commit to merge (content unchanged).
- Fixed: the completeness check called every module's `/v1/meta` itself (spec rule 2: only the orchestrator calls
  modules). The gateway now passes `options.registered_steps`; the static list is only a fallback, now in sync with
  the modules. The eval keeps its own fixture registry (`EVAL_LINEAGE_STEPS`), so its targets stay meaningful.
- Fixed: Explain named the largest POSITIVE segment as "largest contribution" even when the KPI fell (a +6527
  segment for a -42490 revenue drop). Contributions are now ranked in the direction of the change, in one shared
  helper used by the ranking, the field filler and the fact-checker; the amount after "went down" is absolute; the
  explanation cache key includes a logic version so answers produced by the old logic are not reused.
- Fixed: prose deadline (120 s) equalled the gateway budget (120 s), so the stage timed out; now 80 s / 25 s.
- Fixed: "constant" (a logged cleaning strategy) was rejected as an evaluative word; words quoted from the facts pass.
- Owner: on real events the fact-checker rejects step/rule names as claims (`rank:ingest_csv`, `rank:read_parquet`,
  `evaluative:constant`), and in one section the **template text itself fails the fact-check**. Tuned on synthetic
  events; worth a pass on a real `events.jsonl` (any `data/runs/<id>/lineage/events.jsonl`).
- Owner: "row continuity break: dbt_marts wrote 920 rows and dbt_intermediate read 2039" is a false alarm: joins
  legitimately read several inputs (int_order_items reads stg_order_items 1119 + dim_product 920).
- Owner: `audit` takes ~50 s of a ~75 s run (13 calls to the 120B model, some 10-15 s). Consider `llm_fast` for
  section prose, or fewer retries.
- Owner: `data/auditor/explanations/*.json` (39 files from experiments on synthetic data) are committed under `data/`,
  which is for runtime output. Suggest removing them from git and adding `data/auditor/` to `.gitignore`.
- Team decision (contract): coverage is 69.7% because registered steps include **conditional** ones
  (`ingest_sql`/`ingest_api` only for those sources, `type_guard_block` only when something is blocked...). Proposal:
  split `lineage_steps` into always-emitted vs optional in `MetaResponse` (contract change: needs everyone).

## BO3 Profiler + Cleaner

- Fixed: `main.py` ignored the per-module mock switch.
- Fixed: LLM `impute_median` crashed on an int column with no nulls (pandas 3 refuses 612.5 in int64).
- Fixed: full Olist clean 206 s -> 45 s. `.replace(dict)` with thousands of accent fixes on 1M geolocation rows took
  137 s; `.map()` does the same exact-value lookup. Role inference now works on distinct values (and a fixed 200k
  sample for the numeric fraction). Output verified identical on all 9 tables.
- Fixed: `eval/run_all.py` used `parents[3]` (= `/` in the container): `/v1/eval` never ran.
- Owner: the timeout wrapper returns only after the work ends (`with ThreadPoolExecutor` waits), so a "120 s timeout"
  answered at 206 s.
- Owner: `/health` calls the LLM provider on every request (1-5 s). Cache the result.
- Owner: `tests/fixtures/uploads/06_large.csv` (5 MB) is committed though a generator exists.
- Owner: `_load_tables` loads every parquet input and keys it by the last name segment: with `ingest.orders` and
  `clean.orders` both present, the winner depends on dict order. Prefer explicit stage prefixes.

## BO4 Ingest / Validate / Score

- Fixed: repo root was `parents[3]` (= `/` in the container): config never found in Docker.
- Fixed: CSV ingest ignored `expected_schema` str columns: zip `"01037"` became `1037`.
- Fixed: raw validation rejected every raw CSV (dates are text until cleaned). Raw stage = input contract
  (`coerce=True`, values must be convertible); clean stage = strict output contract.
- Fixed: `score_after` overwrote `score_before` (same file name); one file per stage now.
- Fixed: `/v1/eval` import error, and **the eval changed `DATA_DIR` of the live service without restoring it**: every
  later ingest wrote into a deleted temp folder while answering "ok". Restored in a `finally`.
- Owner: quality score barely moves after cleaning (99.0 -> 99.1 on the sample) although the eval shows it reacts to
  heavy corruption (100 -> 88.5). Weights/dimensions may need tuning to show the cleaning gain.

## BO5 Semantic & KPI and BO6 Analyst (were stubs: implemented in bo1/foundation)

- BO5: `compute` (catalog SQL + dimension cuts, `n` per value), `index` / `map_question` (Chroma, embedder name in
  metadata, built-in trigram embedding when no embedder is reachable, closed-menu LLM pick), `suggest_kpis` (draft
  YAML). Eval: Recall@1 0.875, Recall@3 0.906 on 32 questions with the trigram embedder (a semantic embedder, e.g.
  Ollama `nomic-embed-text`, is the next step; the network here blocked downloading one).
- BO6: complete-month detection, trend, robust anomalies, driver decomposition (additive / mix+rate, sums exactly to
  the change), rule-table recommendations, fact-checked narratives under a time budget, dashboard_config.
  Eval: anomaly recall 1.0 / precision 1.0 on 20 planted series, driver sums 200/200.
- Owners of BO5/BO6: please review and take over these modules; rules live in `configs/recommendations/`.

## BO1 (ours), for transparency

- Graph had no profile-after stage (spec: before/after profile diff). Added `profile_after`.
- ETL marts, staging generation, reconciliation and fingerprints: see `services/etl/` and `configs/marts/ecommerce/`.
