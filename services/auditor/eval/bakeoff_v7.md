# v7 frame bake-off

The model selects frame names. Code writes the text. Two cold runs are reported for the 120B.

| arm | model | first try | after retry | fallback | p50 ms | p95 ms | tokens | 429 | identical frames |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| groq-120b run A | openai/gpt-oss-120b | 1.0 | 0.0 | 0.0 | 1201.3 | 1469.5 | 10804 | 0 | 12 |
| groq-120b run B | openai/gpt-oss-120b | 0.95 | 0.0 | 0.05 | 3335.4 | 13831.0 | 10246 | 10 | — |
| groq-20b | openai/gpt-oss-20b | 1.0 | 0.0 | 0.0 | 2178.0 | 3318.6 | 10301 | 0 | — |
| llama-8b | llama3.1:8b | 0.95 | 0.05 | 0.0 | 6425.6 | 11797.5 | 7215 | 0 | — |
| llama-3b | llama3.2:latest | 0.8 | 0.2 | 0.0 | 4213.4 | 8605.7 | 8576 | 0 | — |

Gate: api default is v6. The 120B runs did not both reach first-try 1.00 and fallback 0.00, so the api profile stays on v6.

F3 omitted when offered, published text, 120B run A: 0 of 20.
F6 picked 0 (offered 0). F7 picked 0 (offered 0).

No frame sentence contains a cause, a forecast, a target, or an opinion. Numbers and units are filled from the sheet.
The held-out and fresh captions are not producible by v7. Checker recalls on those sets are unchanged and are listed in the JSON.
