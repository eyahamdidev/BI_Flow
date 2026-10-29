# BO2 traceability: lineage, fact-check, and what the harness measured

The auditor is the only place a reader should have to look to see what happened to a dataset and why a KPI has the value on the screen. Sara, Amine, and Karim get plain language. Every sentence they read is tied to a fact that was already logged. The service does not write `lineage/events.jsonl` (the gateway does that), and it does not open raw tables. It reads the event log, KPI definitions, the lineage graph, and the driver file from the analyst.

The demo explain path is v8. The model receives every logged fact, with its value, in file order. When more than five facts are logged it keeps five and leaves the rest out. It writes the paragraph itself. Python does not rank the facts and does not write that paragraph. Python rejects the paragraph when a number, a direction, a top contributor, or a dropped fact does not match the files, and asks the model to rewrite it, twice. There is no bake-off score for v8. The v7 numbers later in this report measure the older menu, where the model only returned sentence names and Python wrote the text.

## How a run becomes a graph

`POST /v1/run` with `mode: graph` reads `runs/<run_id>/lineage/events.jsonl`. Datasets, warehouse models, KPIs, and insights are nodes. Each transformation is an edge. When an event names its inputs and outputs, those artifacts become the endpoints: a file under `00_ingest` stays on the raw layer even if a cleaning step reads it, `02_clean` is the clean layer, `03_etl` is the warehouse, and a KPI or insight id is its own node. The layer comes from the path, not from the module that happened to emit the event, so a cleaning rule cannot hide the raw table it started from.

Events that only carry a step name, which is what the current mocks do, still produce a graph. Each known step has a stable product node (`raw.tables`, `clean.products`, `dbt.fact_orders`, and so on) and an edge from the previous product when that node was actually logged. If KPI definitions or insights were passed in, and a `compute_kpi` or `detect_anomalies` event exists, those files are expanded into one node per KPI and one node per insight. The auditor does not invent a warehouse table that no event produced.

The JSON file is the shape the Streamlit lineage tab already draws: `id`, `label`, and `layer` on each node, `from`, `to`, and `step` on each edge. A `pyvis` block next to that carries `title`, `level`, and `group` for a hover graph. The schema is `services/auditor/schemas/lineage_graph.schema.json`. `upstream(kpi_id)` walks the graph with NetworkX and returns the raw tables, the cleaning rules on the way into the clean layer, the dbt models, and the KPI SQL.

`mode: audit` turns the same log into `trace_report.json` and `trace_report.md`. Each stage lists the step, the method (`deterministic`, `ml`, or `llm_assisted`), the rule, rows in and out, rows affected, and any duration the run manifest recorded. Each KPI is shown with its definition, SQL, source tables, and the cleaning steps that touch it. Each insight is shown with its facts. The narrative that another module may have written is left out of the fact sheet, so the auditor cannot launder an unchecked sentence into a new one.

Completeness asks every other module for `/v1/meta` and compares `lineage_steps` with the steps that actually appear in the log. If those services are down, it uses the same step list they declare in code today. Anything missing is printed as an untracked transformation. Coverage is the share of registered steps that have at least one event. The target is 100%.

## How a sentence is allowed to contain a number

The language model never sees the raw log. For each report section it receives one fact sheet and `prompts/auditor/section_prose/v3.yaml`. Explain uses `explain_kpi/v6.yaml` unless `options.explain_kpi_version` says otherwise. v1 is a plain instruction and v2 is a few-shot prompt whose example numbers are easy to copy. v3 is the fact-sheet prompt. v4 asks for field ids in brackets. v6 asks for a JSON list of sentences whose only facts are ids, and code fills the value, the unit, and the direction word. Section prose stays at temperature 0.2. v6 runs at temperature 0. The audit report is capped at eight model calls. Explain has a 30 second budget. The audit stops starting new calls after 120 seconds.

After each draft, a checker reads the prose against that one sheet. Thousands separators are ignored and `8` and `8.0` are the same number. A bare number still passes when that number already occurs in the sheet, including inside a period or a rule. A percent does not: `8%` or `8 percent` is kept only when a rate, share, or coverage field holds `8` or `0.08`, so an unrelated count of 8 cannot license a percentage. Direction words live in `services/auditor/app/direction_words.yaml`. They have to agree with the sign of `total_delta`. The list includes went up, went down, climbed, rose, fell, dropped, grew, declined, and the French hausse, baisse, and augmenté. A sentence that names the top driver, including "the largest contribution came from SP", has to name a contribution with the largest delta. The v3 prompts tell the model to use that wording and not to invent a cause. A Brazilian state code, a snake_case category, or a dataset id such as `raw.customers` has to appear in the sheet. A causal connective (`because`, `caused by`, `due to`, `driven by`) is rejected unless the sheet has a `cause` or `rule_id` and the sentence quotes that value. A driver split is not a cause, so "caused by carrier delays" fails even when the sheet mentions the carrier.

If anything is left over, the model is told which claims to drop and is asked again, at most twice. If it is still wrong, or the model cannot be reached, the service publishes a template written by code from the same sheet and records a warning. The run status becomes `partial`. The template is checked with the same function. An optional judge, off unless `options.llm_judge` is set, reads the paragraph with `llm_fast` and may add a warning. It does not override the checker.

`mode: explain` builds the sheet from the KPI definition, `upstream(kpi_id)`, and the driver row for that period (and `compare_to`, when it is set). The model must answer in three to five sentences. If the sheet has no definition, no path, no drivers, and no insight facts, the answer is exactly `not enough logged information` and the model is not called.

## What was measured

`eval/events.jsonl` contains one event for each step the other five modules register, and coverage on that file is 1.0 with nothing untracked. The headline checker result is not the development set. Those 15 paragraphs were written after the rules, and the checker catches all 15 of them. That only shows each rule fires on the sentence written for it. The digit-only check catches 3 of those 15 (0.2).

The number to quote as held-out recall is the figure from before these rules were written: 0.33 (5 of 15). `llama3.2:latest` wrote those captions from one fact sheet. The prompt did not mention the rules. The evaluative words were taken from captions that had already slipped through (`steady`, `important`, `strong`, `key`, `performance`, `critical`, `ability`). After those rules, the same 15 captions score 0.73 (11 of 15). That shows the rules close those gaps. It does not show that the checker generalises. The union with the 20B judge on that same set is 0.87 (13 of 15), and it is a post-fix number for the same reason. Four captions are still open: h02, h04, h06, and h11. False-reject rate on the 30 author-written supported sentences is still 0.0, and the one supported held-out caption is still kept.

A fresh set was written afterwards by `openai/gpt-oss-120b` from the ex10 fact sheet only (`prompts/auditor/adversarial_prose/v2.yaml`). The prompt asked for a claim the notes do not contain and did not list the checker rules. All 15 captions were labelled unsupported by reading that sheet. None is a supported control, so this set does not measure false-reject. The checker catches 1 of 15 (f09, which says "key" and "performance"), so fresh checker recall is 0.0667. The 20B judge fails all 15, so fresh judge recall is 1.0 and the union is 1.0. The other 14 are causes, forecasts, and targets the lists do not name. Those words were not added to the checker.

Twenty explain cases, five KPIs across four periods, each carry two real contributions and three hand-labelled claims (two supported, one with a number in the 900000s that was never logged). The template baseline, which is what readers get when the model fails, passes the number check on all 20 answers, names every expected driver, and agrees with all 60 labels. Faithfulness is 1.0. The unsupported-statement rate after fallback is 0.0. Those are the "after" numbers. Check latency on this set is still under a millisecond (p50 about 0.21 ms, p95 about 0.48 ms). That is the checker, not a model round trip.

Five reviewer slots are in `eval/readability.json` and are still empty, so there is no clarity score. Filling them in without five readers would be a made-up result. The 1.0 first-try rate on the 20 explain cases above is the template baseline. It is true because the template copies the sheet.

The demo path is Groq. `llama-3.3-70b-versatile` returns HTTP 404 on this key, so the large model is `openai/gpt-oss-120b`. `config/models.yaml` sets `api`, `ollama`, and `low_ram` to v7. An `options.explain_kpi_version` value still overrides the profile. The local switch uses the earlier n=20 bake-off, where v7 beat v4: `llama3.1:8b` 0.95 first-try and 0.00 fallback against v4 0.65 and 0.05, and `llama3.2:latest` 0.80 and 0.00 against v4 0.45 and 0.25. The ollama profile's configured model is `qwen2.5:7b-instruct`, which was not in that bake-off.

v6 (`prompts/auditor/explain_kpi/v6.yaml`) is rendered with Jinja2. The model returns `{"sentences":[{"text","ids"}]}` and may use only `kpi.name`, `period.current`, `period.compare`, `drivers.direction`, `drivers.total_delta`, and the label and delta of the top three drivers. Code supplies the value, `definition.unit`, and the direction word. A published explanation has to include `kpi.name`, `drivers.direction`, `drivers.total_delta`, and the top driver label. In v6 that label id is `drivers.top1.label`; `drivers.top.label` counts as the same requirement. A word in `evaluative_words.yaml` is rejected when it sits outside a bracket. A bad id comes back as `unknown id [SC]. Valid ids: ...`. After two retries the template is published.

| arm | model | prompt | first try | after retry | fallback | p50 ms | p95 ms | tokens | 429 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| template | code | — | 1.00 | 0.00 | 0.00 | 2.4 | 3.0 | 0 | 0 |
| Groq | gpt-oss-120b | v4 | 0.40 | 0.20 | 0.40 | 17533 | 39172 | 61039 | 27 |
| Groq | gpt-oss-120b | v6 | 1.00 | 0.00 | 0.00 | 11328 | 12980 | 28665 | 18 |

On the 120B, v6 beats v4, so the API profile defaults to v6. A second v6 run with a cold cache still passed the checker on the first try for all 20. The wording was not stable: 3 of 20 answers were identical. The other 17 changed phrasing, and 8 of those included or dropped a contribution amount. The 20 cases were then run once more into `.cache/llm.sqlite`. That cached sample is a third wording. `eval/faithfulness_template.csv` is the first sample. They are not the same text.

The production client already sends `seed` 7. A paired rerun, still at temperature 0, also sent `reasoning_effort: low`. This model accepts that value (HTTP 200). Each run used its own cold cache. The checker passed on the first try for all 20 in both runs. The wording matched on 6 of 20 (`ex04`, `ex07`, `ex08`, `ex11`, `ex14`, `ex15`). Of the 14 that changed, 6 added or dropped a second driver amount (`ex03`, `ex06`, `ex09`, `ex12`, `ex13`, `ex18`). Every number in both texts is on the fact sheet. Groq does not guarantee the same wording. Checker pass is stable at 20/20. Wording is not.

Explain stores the published text at `data/auditor/explanations/<key>.json`. The key is `sha256` of the KPI, the period, `compare_to`, the fact sheet, the prompt version, the model, and the language. A later call with that key returns the stored text and does not call the model. The lineage event records `explanation_key` and `response_sha256`. The v6 faithfulness CSV still has an empty `supported (1/0)` column (0 of 73 rows), so those v6 sentences were not copied into the store. The paced v7 texts were: 34 files, run 1 of the 20 explain cases plus the synthetic sheets that produced a paragraph. The empty sheet is not stored. It abstains.

One more cold v6 run, after the evaluative-word list and the required-id check, used the same model, temperature 0, seed 7, and `reasoning_effort: low`. First-try pass was 1.00, pass after retry was 0.00, and fallback was 0.00, on all 20 cases. The second contribution amount is optional: the required-id check does not include `drivers.top2.delta`, even when the sheet has a second driver. That is why a later run can still drop or add that amount. The explanation store is what keeps the text a user sees stable. That run did not measure wording stability again.

The judge is `openai/gpt-oss-20b`, a different model from the 3B that wrote the held-out captions and from the 120B that wrote the v6 answers. On the 15 unsupported held-out captions it fails 10, so judge recall is 0.6667. That recall was measured before the evaluative-word rules. Combining it with the checker after those rules gives 0.8667 on the same captions, which is a post-fix number, not a fresh held-out recall. False-reject on the one supported held-out caption is 0.0. On the 30 author-written supported sentences the same judge rejects 2 (`v29` and `v30`), so the judge false-reject rate is 0.0667. Both sentences are supported by the sheet the judge was given, so those two rejects are plain judge errors. The checker still rejects 0 of those 30. The same judge fails 5 of the 20 published 120B v6 answers (`ex04`, `ex08`, `ex10`, `ex11`, `ex19`). That 0.25 is a flag rate, because those answers are not hand-labelled.

The 120B v6 answers are in `eval/faithfulness_template.csv`, one row per sentence, with `supported (1/0)` left empty. They were not labelled here. `eval/score_faithfulness.py` computes the rate after that column is filled. `eval/readability_form.md` has 10 explanations, five from the template and five from that model, shuffled, source hidden. Scores go in `eval/readability.json` under `form_scores`. `eval/score_readability.py` then reports the mean per source. The five-person `scores` list is still empty. A one-reader pilot of the older 3B v4 answers (mean 3.05) is not that panel.

The layers are there so a failure in one place does not have to be trusted. The fact-id layer stops the model choosing a unit. The rule checker still rejects a wrong top driver, a wrong direction, a cause, and an entity the sheet does not name, after the ids have been filled. The judge is a different model from the writer and can only add a warning. The template is what remains when both retries fail, and the fallback rate is the count of how often that happens.

The trace report checks row continuity on the handoff only. A cleaning step may read 100 rows and write 90 of the same dataset. That filter is not a break. A break is the next step reading a count other than the 90 that were written. Explain answers carry a citation list. On v3 those citations are inferred after the fact by overlapping numbers and labels (`citation_method: inferred_overlap`). Two fields that share a value can both be attached. On v4, v6, and v7 the citations are declared by the writer path (`declared_field_id`). On v7 each citation is the frame name and the ids that frame filled.

## v7 frames

v7 (`prompts/auditor/explain_kpi/v7.yaml`, `services/auditor/app/frames.yaml`) does not ask the model to write a sentence. The model returns `{"frames":["F1","F2",...]}`. Code fills `format_field` and `direction_word`. The model is not shown the fact values, only the offered frame names and one-line meanings.

Choices recorded here:

- F5 requires `lineage.cleaning_rules`. The fact sheet has no `lineage.cleaning_steps`.
- F4 also requires `kpi.name`, because that bracket is in the sentence.
- French F1 uses the existing `direction_word`, so a rise reads "a en hausse de", not a conjugated verb.
- The rank rule skips a match preceded by "second", "third", or "deuxième". Without that, F3 ("the second largest contribution came from RJ") was scored as a claim that RJ was the top driver. Held-out recall on the tuned captions stayed 0.7333 after this change.
- `seed` 7 is already sent by the shared client. v7 adds `reasoning_effort=low` only when `LLM_PROVIDER=api`. A 400 drops that field for the rest of the process.
- If the checker or the evaluative list rejects a rendered frame sentence, the run records that as a finding and publishes the frame fallback. None of the bake-off rows that reached the model carried that warning.
- The gate uses both cold 120B runs. One good run is not enough.
- Ollama was down when the bake-off first asked for tags. The local arms were run after `ollama serve` came up. The ollama profile stays on v4 because its configured model is `qwen2.5:7b-instruct`, which was not measured, and because the 3B arm missed the gate anyway.

A frame is offered only when every required id is non-empty. A valid answer has 3 to 5 names, F1 first when offered, no duplicates, and F3 whenever a second driver exists. After two bad replies the published text is F1, F2, F3 if offered, and F5 if offered.

| arm | model | prompt | first try | after retry | fallback | p50 ms | p95 ms | tokens | 429 | identical frame lists |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| code | template | — | 1.00 | 0.00 | 0.00 | 2.4 | 3.0 | 0 | 0 | — |
| Groq | gpt-oss-120b | v4 | 0.40 | 0.20 | 0.40 | 17533 | 39172 | 61039 | 27 | — |
| Groq | gpt-oss-120b | v6 | 1.00 | 0.00 | 0.00 | 11328 | 12980 | 28665 | 18 | 6 of 20 texts, earlier paired run |
| Groq | gpt-oss-120b | v7 run A | 1.00 | 0.00 | 0.00 | 1201.3 | 1469.5 | 10804 | 0 | 12 of 20 |
| Groq | gpt-oss-120b | v7 run B | 0.95 | 0.00 | 0.05 | 3335.4 | 13831.0 | 10246 | 10 | same pair |
| Groq | gpt-oss-20b | v7 | 1.00 | 0.00 | 0.00 | 2178.0 | 3318.6 | 10301 | 0 | — |
| local | llama3.1:8b | v7 | 0.95 | 0.05 | 0.00 | 6425.6 | 11797.5 | 7215 | 0 | — |
| local | llama3.2:latest | v7 | 0.80 | 0.20 | 0.00 | 4213.4 | 8605.7 | 8576 | 0 | — |

That first gate did not pass. Run B published a fallback for `ex12` (`first_try_pass` was null, which is the path taken when the client stops before a selection is rejected) during a run with 10 HTTP 429 responses. The published frames were the deterministic list F1, F2, F3, F5. The 8B and 3B arms did reach fallback 0.00. First-try was 0.80 on the 3B and 0.95 on the 8B, both on n=20, which is why `ollama` and `low_ram` moved to v7 even though `qwen2.5:7b-instruct` itself was not measured.

Frame lists matched on 12 of 20 cases in that unpaced pair, and the text matched on those same 12. Four of the eight differences were the same frames in a different order. Rendering now ignores that order.

### Paced rerun

Published sentences are rendered in fixed order F1 through F7. Validation is unchanged: F1 has to be first when it is offered, F3 has to be present when it is offered, the answer has 3 to 5 names when at least three frames are offered, names cannot repeat, and a name has to be one of the offered frames.

The rerun used concurrency 1, temperature 0, seed 7, and `reasoning_effort=low`. The minimum gap between call starts was 8 seconds (`BIFLOW_MIN_INTERVAL`). The shared client already sleeps `min(Retry-After, 30)`. The auditor sleeps any remainder above 30 seconds so a longer header is still honoured, and it logs every 429 with the case id. This run did not receive a 429, so that remainder path was not exercised on Groq. The tests cover a logged 429 and a header of 45 seconds.

Three cold caches, n=20, `openai/gpt-oss-120b`:

| run | first try | fallback | p50 ms | p95 ms | tokens | 429 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.00 | 0.00 | 8020.4 | 9792.5 | 10620 | 0 |
| 2 | 1.00 | 0.00 | 8033.8 | 10216.3 | 10575 | 0 |
| 3 | 1.00 | 0.00 | 7998.9 | 8844.7 | 10663 | 0 |

The p50 is about 8 seconds because the timer includes the minimum gap between call starts. The fastest call in each run was 2128.1 ms, 1359.5 ms, and 1520.1 ms. Those are the calls that did not wait out a full gap.

The strict gate passes: all three runs are first-try 1.00 and fallback 0.00. The same gate with 429 and timeout fallbacks removed also passes. Nothing was removed, because there was no 429 and no timeout. `api` is therefore v7. Before pacing, the gate failed on the two-run rule because run B was 0.95 with one fallback during 10 rate-limit responses.

Identical frame sets on that paced run, before F2 and F6 were required, were 14 of 20. The six that moved were `ex02`, `ex03`, `ex11`, `ex12`, `ex16`, and `ex20`, all on whether F4 or F5 was included.

F1, F2, F3, and F6 are now mandatory when they are offered. The prompt says so, and a selection that drops one of them is rejected and retried. The fallback list includes F6 when a rule id was logged. F4, F5, and F7 stay optional, and the answer is still at most 5 frames, so a sheet that offers all seven can keep only one of F4, F5, or F7 beside the four required names.

The required-frame rerun, same pacing, three cold caches, n=20:

| run | first try | fallback | p50 ms | p95 ms | tokens | 429 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.00 | 0.00 | 7962.7 | 12308.5 | 11471 | 0 |
| 2 | 1.00 | 0.00 | 8024.5 | 9724.2 | 11305 | 0 |
| 3 | 1.00 | 0.00 | 8100.6 | 9543.1 | 11492 | 0 |

Both gates pass again. No 429 and no timeout. Identical frame sets: 19 of 20. The only difference is `ex10` on run 3, which dropped F5 and kept F1, F2, F3, F4. F2 was present in every published selection on the 20 explain cases. Those cases do not offer F6, because they have no `rule_id`. On the synthetic sheets, F6 was offered 4 times and selected 4 times (`syn05`, `syn07`, `syn12`, `syn15`). `syn13` still left out F7. F7 is optional. `faithfulness_v7.csv` was regenerated from run 1 of this rerun, and the supported and omission cells are blank again. The store was rewritten with those texts.

The explanation store is what makes a later request return the same paragraph. The store key includes the language.

`eval/faithfulness_v7.csv` is run 1 of this paced sample, then the 15 synthetic sheets. Supported and omission cells are blank (0 of 89 explain sentences, 0 of 20 explain omission rows, 0 of 62 synthetic sentences, 0 of 15 synthetic omission rows). `eval/score_faithfulness_v7.py` reports the two sets separately, each with n and a 95% Wilson interval, and warns that n=20 is wide. `eval/faithfulness_v7_sheets.md` has the sheet next to the published text. Those labels are filled by a person. They are not model-generated. The same is true of the five readability scores.

`eval/demo_check.py` was run with the model URL pointed at `127.0.0.1:9`, which refused the connection. Three stored cases (`ex01`, `ex02`, `ex03`) returned the stored text with no model call. A case that was not stored returned source `fallback` and the warning that the language model was unavailable. v7's fallback is the fixed frame list. An empty sheet returned "not enough logged information" with no model call. All five checks passed.

### Synthetic shapes

Fifteen hand-written sheets in `eval/synthetic_sheets/sheets.json`. They cover shapes. They are not a sample, and no rate is claimed from them. One 120B pass, cache cold. HTTP 429 count 0. Every non-empty subset of the offered frames passed the safety check: after the filled values are removed, no digit remains and every remaining word is in the frame text.

| sheet | offered | chosen | first try | fallback | direction | safety |
| --- | --- | --- | --- | --- | --- | --- |
| syn01 decrease en | F1–F5 | F1–F5 | yes | no | went down | pass |
| syn02 flat en | F1–F5 | F1–F5 | yes | no | was unchanged | pass |
| syn03 one driver | F1 F2 F4 F5 | same | yes | no | — | pass |
| syn04 three drivers en | F1–F5 | F1–F5 | yes | no | — | pass |
| syn05 rule en | F1–F6 | F1–F4 | yes | no | — | pass |
| syn06 caveat en | F1–F5 F7 | F1 F3 F7 | yes | no | — | pass |
| syn07 both en | F1–F7 | F1–F5 | yes | no | — | pass |
| syn08 no lineage | F1–F4 | F1–F4 | yes | no | — | pass |
| syn09 empty | none | abstain | no model call | no | — | pass |
| syn10 decrease fr | F1–F5 | F1–F4 | yes | no | en baisse | pass |
| syn11 flat fr | F1–F5 | F1–F3 | yes | no | inchangé | pass |
| syn12 rule fr | F1–F6 | F1–F5 | yes | no | — | pass |
| syn13 caveat fr | F1–F5 F7 | F1–F5 | yes | no | — | pass |
| syn14 three drivers fr | F1–F5 | F1–F5 | yes | no | — | pass |
| syn15 both fr | F1–F7 | F1–F4 | yes | no | — | pass |

F6 was offered on 4 sheets and selected on 0. Rendering F6 by itself produces "The logged rule for this change is late_delivery." F7 was offered on 4 sheets and selected on 1 (`syn06`). That sentence is "Caveat on record: Delivered orders only." `syn06` also left out F2, the largest contribution, and kept F3. The validator requires F3 when a second driver exists. It does not require F2, F4, F5, F6, or F7. Leaving those out is the omission the blank column is there to label.

The empty sheet returned "not enough logged information" and did not call the model. A decrease renders "went down" / "en baisse". A flat month (`total_delta` 0) renders "was unchanged" / "inchangé".

### What each layer is for

Frames fix the sentence. The model only picks names, and code fills numbers, units, and the direction word, so a fresh wording the checker has never seen cannot appear. The explain screen opens each sentence onto the fact id, the logged value, the lineage event id when one was logged, the KPI SQL, and the source tables. A missing event stays blank. The rule checker is the backup on that rendered text. The different-model judge is optional. On the 30 supported sentences it false-rejects 2 of 30 (0.0667), and both are judge errors. The template, for v7 the fixed frame list, is what is published when the model does not return a valid selection or the client gives up. A 429 or a timeout on that path is labelled as the cause.

Checking bad free text generalised badly. Held-out recall before the evaluative rules was 0.33 (5 of 15). After rules written from those misses, the same captions score 0.73 (11 of 15). That is not a fresh result. The fresh 120B set scores 0.0667 (1 of 15). Frames remove that failure class by construction: the model never writes the sentence.

F3 was offered on all 20 sheets. The published selection omitted it 0 times, on every arm, including the `ex12` fallback. F6 and F7 were offered 0 times: these sheets have no `rule_id` and no `definition.caveats`. Picks were 0, which matches that expectation and does not test a bad choice of F6. F4 and F5 are optional, so a run can leave out the definition and the sources.

No frame text contains a cause, a forecast, a target, or an opinion. A test renders every non-empty subset of the offered frames for all 20 sheets, in English and French. After the substituted values are removed, no digit remains, and every remaining word is part of the frame. None of the 15 held-out unsupported captions or the 15 fresh captions equals any of those renderings. They are not producible by v7. The old checker was not changed for that comparison: before the evaluative rules it caught 5 of 15 (0.33); after rules written from those misses it catches 11 of 15 (0.73) on the same captions; on the fresh 120B set it catches 1 of 15 (0.0667). The evaluative list was built from h05, h08, h09, h12, h13, and h15. The direction list was written with the checker, not from those misses. Recognising bad free prose did not generalise. Frames remove that class because the model never writes the sentence.

## Limitations

Quote held-out recall 0.33 (5 of 15), from before the evaluative-word rules. Quote checker false-reject rate 0.0 on the 30 supported sentences. The 0.73 (11 of 15) and the 0.87 union are what the same captions score after rules written from those misses. The fresh 120B set has checker recall 0.0667 and judge recall 1.0. Do not quote the development set's 15/15. The paced v7 gate did pass, on three cold 120B runs, first-try 1.00 and fallback 0.00, so `api` is v7. The earlier unpaced run B (0.95, one fallback, 10 HTTP 429 responses) is the before-pacing result. Frame choice is still not stable: identical sets on 14 of 20. Selection quality is unmeasured until the v7 CSV is labelled. n=20 gives a wide Wilson interval. The synthetic sheets are shape coverage, not a larger sample. Local v7 numbers are also n=20. The 70B id returned HTTP 404, so the large arm is `openai/gpt-oss-120b`. MLflow was not run. Readability scores and faithfulness labels are entered by a person, not generated by the model.

v6 can still publish "impacted by slower sales" or "meet our targets" beside the required ids. h04 and h11 are that class. h02 and h06 are a typed number with the wrong unit, which v6 and v7 both block because code writes the unit. v7 cannot publish h04 or h11 either: those words are not in any frame. The wording that remains is the frame text, which is plain and fixed. Published order is F1 through F7, so F2 can no longer be printed after F3. A wrong selection can still mislead by leaving out F2, F4, F5, F6, or F7. `syn06` did that: it kept F3 and left out F2. It cannot leave out F3 when a second driver was logged. Whether the chosen frames are the right explanation is not measured until `faithfulness_v7.csv` is labelled. The older `faithfulness_template.csv` is still unlabelled as well. v7 does not produce a free-form insight.

On v6, the second contribution amount is optional. The v6 required-id check does not include `drivers.top2.delta`. The explanation store is what makes the shown text stable. The 20B judge's false-reject rate on the 30 supported sentences is 0.0667, and both rejects are plain judge errors. The five flagged v6 answers (`ex04`, `ex08`, `ex10`, `ex11`, `ex19`) are still unlabelled. The 70B model was not available (HTTP 404). The sample is 20 explain cases written for this harness. Reviewer scores from the five-person panel are empty. Whether the event log itself was tampered with is outside this service. The gateway is the only writer, and a hash chain on those events would belong to that writer.
