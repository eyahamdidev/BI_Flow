# Auditor (lineage, trace report, Explain)

| | |
|---|---|
| Owner | **BO2** |
| Module name | `auditor` |
| Port | `8102` |
| Stack | networkx, pyvis data, jinja2 |
| LLM | yes (via `biflow_llm`, always with a fallback) |

## Modes (`POST /v1/run`, field `mode`)

| mode | what it does |
|---|---|
| `graph` | Build lineage_graph.json (nodes/edges) from lineage/events.jsonl. |
| `audit` | Structured trace report first, then LLM prose per section from a fact sheet + number fact-check. Writes trace_report.md/json. |
| `explain` | options: kpi_id, period, compare_to. Build a fact sheet (definition + lineage path + drivers), LLM writes 3-5 sentences, fact-check; abstain if sheet empty. |

## Run it

```bash
# from repo root
make venv SERVICE=auditor                 # creates services/auditor/.venv and installs deps
make run SERVICE=auditor                  # uvicorn on :8102 (BIFLOW_MOCK=1 by default)
BIFLOW_MOCK=0 make run SERVICE=auditor    # real handlers (raise NotImplementedError until you write them)
make test SERVICE=auditor                 # contract test
```

## Definition of done for this module

See the spec sections for BO2 in `docs/BIFlow_Technical_Spec.md` (acceptance criteria and metrics are the definition of done).

## TODO checklist

- [ ] Lineage graph builder + upstream(kpi_id)
- [ ] Structured trace report (per stage / KPI / insight)
- [ ] Prose layer + number fact-check (regex+code)
- [ ] Explain this KPI (fact sheet -> 3-5 sentences, abstain when empty)
- [ ] Completeness test vs each module's /v1/meta lineage_steps

## Folder map

```
app/main.py        wiring (do not change the endpoints)
app/handlers.py    YOUR CODE: one function per mode
mock/<mode>.json   fixture served when BIFLOW_MOCK=1 (keep it in sync with the real output shape)
prompts/           versioned prompts (see prompts/_template.yaml at repo root)
eval/              labelled sets + eval script used by POST /v1/eval
tests/             contract test (+ yours)
```
