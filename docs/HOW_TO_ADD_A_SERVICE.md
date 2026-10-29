# How to add (or implement) a service

1. Copy a folder from `services/` (they are all identical in shape) and rename it.
2. In `app/main.py` list your modes and handlers; `service_kit.create_app` gives you `/health`, `/v1/meta`, `/v1/run`, `/v1/eval`.
3. Write `mock/<mode>.json` first (the shape the real handler will return). Keep `{run_id}` in artifact paths.
4. Add a stage to `services/gateway/app/graph.yaml` and a URL env var (`URL_<MODULE>`).
5. `make venv SERVICE=<name> && make test SERVICE=<name>` (contract test is already there).
6. Implement handlers one by one. Flip `BIFLOW_MOCK=0` for your module only when the real handler works:
   `BIFLOW_MOCK=0 make run SERVICE=<name>`.
7. Handler template:

```python
from biflow_contracts import RunRequest
from biflow_contracts.biflow_llm import chat_text, drain_calls   # only if you need an LLM

def clean(req: RunRequest) -> dict:
    src = DATA_DIR / req.inputs["ingest.orders"]            # inputs are paths relative to DATA_DIR
    ...                                                      # compute with pandas / sklearn (deterministic)
    return {
        "status": "ok",
        "outputs": [{"name": "orders", "kind": "parquet", "path": f"runs/{req.run_id}/02_clean/orders.parquet", "rows": n}],
        "metrics": {"rows_dropped": 0},
        "lineage_events": [...],                              # one per transformation
        "llm_calls": drain_calls(),
    }
```
