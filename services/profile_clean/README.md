# Profiler + Cleaner

| | |
|---|---|
| Owner | **BO3** |
| Module name | `profile_clean` |
| Port | `8103` |
| Stack | pandas, scikit-learn, scipy, pyyaml (optional ydata-profiling minimal=True) |
| LLM | yes (via `biflow_llm`, always with a fallback) |

## Modes (`POST /v1/run`, field `mode`)

| mode | what it does |
|---|---|
| `profile` | Profile every table (types, nulls, dupes, outliers, FK orphans). options.stage=before|after. Writes profile.json (+ optional profile.html). |
| `clean` | Rule layer (YAML) + ML layer (imputers/outliers) + advisory LLM layer (closed menu). Writes cleaned parquet, quality_log.json, review_queue.json. in - dropped = out. |

## Run it

```bash
# from repo root
make venv SERVICE=profile_clean                 # creates services/profile_clean/.venv and installs deps
make run SERVICE=profile_clean                  # uvicorn on :8103 (BIFLOW_MOCK=1 by default)
BIFLOW_MOCK=0 make run SERVICE=profile_clean    # real handlers (raise NotImplementedError until you write them)
make test SERVICE=profile_clean                 # contract test
```

## Definition of done for this module

See the spec sections for BO3 in `docs/BIFlow_Technical_Spec.md` (acceptance criteria and metrics are the definition of done).

## TODO checklist

- [ ] Profiler (column/table/cross-table) + before/after diff
- [ ] Rule layer driven by `cleaning_rules` in configs/datasets/olist.yaml
- [ ] ML layer: median/KNN/Iterative imputers, IQR/MAD/LOF/IsolationForest (flag, don't delete)
- [ ] Advisory LLM layer: closed-menu JSON, applied only if YAML allows, else review_queue.json
- [ ] Corruption generator + imputer/outlier benchmark (eval/)
- [ ] Row reconciliation: in - dropped = out, every dropped id logged

## Folder map

```
app/main.py        wiring (do not change the endpoints)
app/handlers.py    YOUR CODE: one function per mode
mock/<mode>.json   fixture served when BIFLOW_MOCK=1 (keep it in sync with the real output shape)
prompts/           versioned prompts (see prompts/_template.yaml at repo root)
eval/              labelled sets + eval script used by POST /v1/eval
tests/             contract test (+ yours)
```
