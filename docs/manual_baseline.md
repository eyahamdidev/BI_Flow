# Manual baseline: how long does the same prep take by hand? (BO1)

BO1's claim is "time-to-insight reduced". That needs a number on both sides: the automated run (measured by
`biflow bench`) and the **same work done by hand**, measured by a person. This page is the protocol; the result goes
in [`manual_baseline.yaml`](manual_baseline.yaml), which `biflow bench` reads to print the manual/automated ratio.

## Rules (so the comparison is fair)

- **Who:** a team member who knows pandas but did not write the BIFlow modules (closest to "Sara, BI analyst").
- **What:** exactly the outputs the pipeline produces, on the **full** Olist data (`data/raw/olist/`), from raw CSVs to
  the numbers. No copying code from `services/` or `configs/marts/` (that would be timing the reuse of our work).
- **Tools:** a Jupyter notebook, pandas, Google/docs allowed. No LLM assistant (the pipeline's LLM steps are measured separately).
- **Timing:** a stopwatch per step, pauses excluded. Write the minutes down at the end of each step.
- **Done =** the step's check passes (see table). Debugging time counts: it is part of real manual work.

## Steps to time

| # | step (YAML key) | done when |
|---|---|---|
| 1 | `load` | the 9 CSVs are loaded with correct types (zip codes keep leading zeros, dates parsed) |
| 2 | `profile` | a per-table summary of nulls, duplicates and suspicious values exists |
| 3 | `clean` | duplicates removed, missing categories handled, English category names added, impossible values flagged |
| 4 | `model` | one table with one row per order: payment total, main payment type, delivery days, delay, review score, main category, customer state |
| 5 | `check` | row count of that table equals the number of distinct orders; spot-check 3 orders by hand |
| 6 | `kpis` | monthly revenue, orders, average delivery days, late-delivery rate, average review score, for delivered orders |
| 7 | `explain` | a written note: which cleaning steps changed which tables, and how one KPI is computed (the "trace") |

Step 7 matters: the pipeline produces the lineage and audit trail automatically, so the manual side must produce
an equivalent written trace, or the comparison flatters the manual process.

## How to record

Fill `docs/manual_baseline.yaml` (minutes, decimals allowed), commit it, then run `biflow bench`: the report shows
`manual minutes vs automated minutes (xRATIO)`. Keep the notebook in `docs/manual_baseline_notebook.ipynb` as evidence.
