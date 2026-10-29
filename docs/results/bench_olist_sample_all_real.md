# BIFlow benchmark: olist_sample (3 runs)

Commit `c0be6de`, provider `api`, config sha256 `da85f6c5267f`. Statuses: ok, ok, ok.

## End to end

| metric | value |
|---|---|
| end-to-end p50 | 114.96 s |
| end-to-end p95 | 142.51 s |
| cold run (empty LLM cache) | 142.51 s, of which LLM 103.39 s |
| cached runs p50 | 107.94 s, of which LLM 59.84 s |
| `--resume --from analyse` | 109.7 s (4.6% less than a full run) |
| reproducible (mart fingerprints identical in every run) | yes |
| manual baseline vs automated | not measured yet (docs/manual_baseline.yaml) |

## Per stage (seconds)

| stage | source | p50 | p95 |
|---|---|---|---|
| ingest | real | 0.6 | 1.15 |
| validate_raw | real | 0.41 | 0.46 |
| profile | real | 1.03 | 1.31 |
| score_before | real | 0.43 | 0.64 |
| clean | real | 1.89 | 3.19 |
| profile_after | real | 1.28 | 1.44 |
| validate | real | 0.36 | 0.38 |
| score_after | real | 0.72 | 0.79 |
| etl | real | 13.84 | 14.12 |
| kpi_compute | real | 0.36 | 0.44 |
| kpi_index | real | 0.08 | 0.1 |
| analyse | real | 3.55 | 14.67 |
| dashboard_config | real | 0.12 | 0.14 |
| lineage_graph | real | 0.06 | 0.07 |
| audit | real | 86.7 | 91.99 |

LLM seconds by stage in the cold run: clean 0.85, analyse 25.86, audit 64.84, summarize 11.84
