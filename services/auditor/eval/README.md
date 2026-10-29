# Auditor evaluation

`POST /v1/eval` runs `app/eval_runner.py` with no language model.

| File | What it measures |
|---|---|
| `events.jsonl` | One event for every step the other modules register. Lineage coverage should be 1. |
| `bad_prose.json` | Development set, written with the rules in view. Do not quote its detection rate as the result. |
| `valid_prose.json` | Thirty supported sentences. False-reject rate. |
| `held_out_prose.json` | Sixteen captions from `llama3.2:latest`. The prompt did not include the checker rules. Labels were added by reading the sheet. |
| `held_out_raw.json` | The model output those captions were taken from. |
| `explain_cases.json` | 20 `(kpi, period)` cases, each with an expected driver list and hand-labelled claims. Rebuild with `python eval/make_cases.py`. |
| `readability.json` | Slots for five non-technical reviewers (1–5). Left empty until that review happens. |

Targets checked by the harness: lineage coverage 100%, fact-check pass rate on the template baseline at least 95%, unsupported-statement rate 0, planted-bad detection 100%, faithfulness 1 on the labelled claims.
