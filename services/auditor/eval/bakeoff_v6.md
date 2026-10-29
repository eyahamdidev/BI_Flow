# Explain bake-off

Demo path: Groq `openai/gpt-oss-120b`, prompt v6. `llama-3.3-70b-versatile` returned HTTP 404. Small local models can't follow v6, so they use v4 (`config/models.yaml`).

| arm | model | prompt | first try | after retry | fallback | p50 ms | p95 ms | tokens | 429 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| template | code | — | 1.00 | 0.00 | 0.00 | 2.4 | 3.0 | 0 | 0 |
| Groq | gpt-oss-120b | v4 | 0.40 | 0.20 | 0.40 | 17533 | 39172 | 61039 | 27 |
| Groq | gpt-oss-120b | v6 | 1.00 | 0.00 | 0.00 | 11328 | 12980 | 28665 | 18 |
| Groq cold rerun | gpt-oss-120b | v6 | 1.00 | — | 0.00 | — | — | — | — |

The cold rerun matched 3 of 20 answers exactly. Checker first-try stayed 1.00.

Judge `openai/gpt-oss-20b` on the 15 unsupported held-out captions: recall 0.6667. Checker recall 0.3333. Union 0.6667. False-reject on the one supported caption 0.0. The same judge flagged 5 of 20 published v6 answers (0.25). That flag rate is not a labelled recall.
