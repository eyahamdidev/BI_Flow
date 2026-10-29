# Analyst (+ dashboard config)

| | |
|---|---|
| Owner | **BO6** |
| Module name | `analyst` |
| Port | `8106` |
| Stack | pandas, scipy, statsmodels, scikit-learn |
| LLM | yes (via `biflow_llm`, always with a fallback) |

## Modes (`POST /v1/run`, field `mode`)

| mode | what it does |
|---|---|
| `analyse` | Trend (slope + STL), anomalies (MAD baseline), driver decomposition (sums to delta), rule-table recommendations, LLM narrative from facts only. Writes insights.json + drivers.json. |
| `dashboard_config` | Generate dashboard_config.json (tiles, charts, dimensions) from kpi_definitions.json + insights.json. |

## Run it

```bash
# from repo root
make venv SERVICE=analyst                 # creates services/analyst/.venv and installs deps
make run SERVICE=analyst                  # uvicorn on :8106 (BIFLOW_MOCK=1 by default)
BIFLOW_MOCK=0 make run SERVICE=analyst    # real handlers (raise NotImplementedError until you write them)
make test SERVICE=analyst                 # contract test
```

## Definition of done for this module

See the spec sections for BO6 in `docs/BIFlow_Technical_Spec.md` (acceptance criteria and metrics are the definition of done).

## TODO checklist

- [ ] Trend: linear slope + p-value, STL
- [ ] Anomalies: MAD baseline, STL residual, IsolationForest
- [ ] Driver decomposition (unit test: sums to delta)
- [ ] Recommendation rule table (configs/recommendations/) + LLM rewrite
- [ ] dashboard_config generator
- [ ] Streamlit dashboard lives in services/dashboard (also BO6)

## Folder map

```
app/main.py        wiring (do not change the endpoints)
app/handlers.py    YOUR CODE: one function per mode
mock/<mode>.json   fixture served when BIFLOW_MOCK=1 (keep it in sync with the real output shape)
prompts/           versioned prompts (see prompts/_template.yaml at repo root)
eval/              labelled sets + eval script used by POST /v1/eval
tests/             contract test (+ yours)
```
