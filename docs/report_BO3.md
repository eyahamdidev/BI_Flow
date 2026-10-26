# BO3 report: profile_clean

**Measurement scope:** Unless a section says otherwise, numbers below come from **`FAKE_LLM=1`**, the **`tests/fixtures/olist_mini`** / synthetic datasets, or local `eval/run_all.py --fast` — not from live API LLMs or full Olist raw CSVs in CI.

## Profiling approach

Deterministic pandas profiling per column (dtype, null rate, distinct count, numeric stats, IQR outlier counts, light pattern checks) and per table (duplicate rows/keys). FK orphan rates come from `relationships:` in the dataset YAML. Outputs: `profile.json`, optional `profile.html` (ydata-profiling, non-blocking), and after clean `profile_diff.json` / `profile_diff.md`.

## Rule / ML / LLM layering

1. **Rules (YAML):** dates, trim, renames, dedupe, category translation, null strategies, impossible values — all logged in `quality_log.json` with undo parquets for value changes.
2. **ML:** median/KNN/iterative imputation and IQR/MAD/IsolationForest/LOF outlier **flags** per YAML; fixed seeds.
3. **LLM (advisory only):** closed menu JSON validated by pydantic; auto-apply only if action is in YAML `allowed_actions`; otherwise `review_queue.json`. Code never delegates arithmetic to the model.

## Closed menus and allow-lists

Prevents unsafe automation (e.g. `drop_column` on keys). Adversarial fixture tests confirm `order_id` suggestions land in review, not in data.

## Reversibility and reconciliation

Each table enforces `rows_in - rows_dropped_logged == rows_out` with `silent_deletions` in metrics (target 0). Undo parquets under `02_clean/_undo/`.

## Results (mini fixture, `FAKE_LLM=1`, from `eval/results/last_eval_metrics.json` when generated locally)

| Benchmark | Headline | Notes |
|-----------|----------|--------|
| Imputation RMSE (median) | 1515.65 | `olist_mini`-scale synthetic table |
| Imputation RMSE (KNN) | 2153.44 | same fixture; KNN worse than median here |
| Outlier F1 (IQR) | 1.0 | tiny spike sample |
| Outlier F1 (IsolationForest) | 0.67 | same tiny sample |
| LLM validity rate (fake) | 0.5 | stub LLM path only |
| Unsafe auto-applied | 0 | adversarial id-column tests |
| Row reconciliation | 100% | unit/integration + cross-dataset safety tests |

## Cross-dataset safety (synthetic Titanic/Iris fixtures, `FAKE_LLM=1`)

From `tests/test_cross_dataset_safety.py` / playground runs on fixture CSVs (891-row Titanic, 150-row Iris): **`silent_deletions == 0`**, row accounting reconciles, dtype guard blocks unsafe imputation on ids/categoricals. Exact imputation/outlier counts for a given run are in that run’s `quality_log.json` and PDF report (artifact-sourced, not LLM).

## PDF report samples (playground, `FAKE_LLM=1`, local timing)

| Dataset | PDF generation (incl. pipeline) | Source |
|---------|-----------------------------------|--------|
| Titanic fixture | ~3.2 s | `eval/report_samples/timings.txt` |
| Iris fixture | ~3.0 s | same |
| 500k-row summary run | ~25 s | parquet metadata + aggregates only; not committed |

Sample files: `services/profile_clean/eval/report_samples/titanic.pdf`, `iris.pdf`, `messy_dirty_csv.pdf`.

## Failed attempts / limits

- KNN imputation lost to median on the mini fixture (higher RMSE).
- IsolationForest/LOF lower precision than IQR on tiny spike sample.
- Live 3B/70B model sweep **not_measured_live** (see README eval-live).
- French `lang=fr` diff text not fully translated.

## Olist-specific handling (YAML-driven)

Undelivered delivery dates flagged (`delivery_missing_flag`), translation gaps + `pc_gamer` mapping, geolocation zip dedupe, review `has_comment`, product weight KNN impute + flag, column renames for `product_name_lenght` typos — all in `configs/datasets/olist.yaml`.
