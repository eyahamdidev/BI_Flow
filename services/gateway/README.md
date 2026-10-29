# Gateway / Orchestrator

Owner **BO1**. Port `8000`. The only component that calls modules.

- `app/graph.yaml`: stage -> module -> mode table (edit here to change the pipeline)
- `app/runner.py`: sequential runner, retries, `--resume`, lineage writer, run manifest
- `app/main.py`: `/api/runs`, `/api/runs/{id}`, `/api/explain` (used by the dashboard)
- `app/cli.py`: `python -m app.cli run --dataset olist`

Module URLs come from env (`URL_ETL`, `URL_AUDITOR`, `URL_PROFILE_CLEAN`, `URL_INGEST_QUALITY`, `URL_SEMANTIC_KPI`, `URL_ANALYST`).

## TODO (BO1)
- [ ] Port the loop in `runner.py` to LangGraph nodes (state = PipelineState, conditional edge on failure)
- [ ] Per-stage timing table + manual-baseline benchmark
- [ ] Optional MLflow logging
- [ ] `/v1/eval` harness: run every module's eval and render one results table
- [ ] Prompt registry check script (fail CI if a prompt used in code has no file)
