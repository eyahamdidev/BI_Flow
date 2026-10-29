# BIFlow benchmark: olist_sample (5 runs)

Commit `a6f26be`, provider `api`, config sha256 `e9b9aa03b85f`. Statuses: ok, ok, ok, ok, ok.

## End to end

| metric | value |
|---|---|
| end-to-end p50 | 22.81 s |
| end-to-end p95 | 32.53 s |
| cold run (empty LLM cache) | 32.53 s, of which LLM 4.37 s |
| cached runs p50 | 22.56 s, of which LLM 2.91 s |
| `--resume --from etl` | 21.34 s (6.4% less than a full run) |
| reproducible (mart fingerprints identical in every run) | yes |
| manual baseline vs automated | not measured yet (docs/manual_baseline.yaml) |

## Per stage (seconds)

| stage | source | p50 | p95 |
|---|---|---|---|
| ingest | real | 0.47 | 0.63 |
| validate_raw | real | 0.32 | 0.67 |
| profile | real | 1.06 | 1.44 |
| score_before | real | 0.37 | 1.09 |
| clean | real | 2.02 | 5.5 |
| validate | real | 0.39 | 0.43 |
| score_after | real | 0.69 | 0.99 |
| etl | real | 13.75 | 18.26 |
| kpi_compute | mock | 0.0 | 0.0 |
| kpi_index | mock | 0.0 | 0.0 |
| analyse | mock | 0.0 | 0.0 |
| dashboard_config | mock | 0.0 | 0.0 |
| lineage_graph | mock | 0.0 | 0.0 |
| audit | mock | 0.0 | 0.0 |

LLM seconds by stage in the cold run: clean 1.54, summarize 2.83
