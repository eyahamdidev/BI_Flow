"""Profiler + Cleaner: owner BO3. Port 8103."""
from __future__ import annotations

import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

import httpx
from biflow_contracts.models import CONTRACT_VERSION, ErrorInfo, EvalResponse, MetaResponse, RunRequest, RunResponse
from biflow_contracts.service_kit import create_app
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import handlers as h
from .config import TIMEOUT_CLEAN_S, TIMEOUT_PROFILE_S
from .errors import BadInputError, ProfileCleanError, TimeoutError
from .eval_runner import run_eval_subset

LINEAGE_STEPS = sorted(
    {
        "profile_tables",
        "profile_diff",
        "parse_dates",
        "trim_strings",
        "rename_columns",
        "drop_exact_duplicates",
        "dedupe",
        "dedupe_geolocation",
        "translate_category_names",
        "category_mapping_fixes",
        "null_strategy",
        "flag_impossible_values",
        "impute_numeric",
        "detect_outliers",
        "impute_categorical",
        "type_guard_block",
        "sentinel_to_null",
        "standardise",
        "category_map",
        "llm_advisory",
    }
)

PROMPT_VERSIONS = {
    "profile_clean.suggest_advisory": "v2",
}

_base = create_app(
    module="profile_clean",
    handlers={"profile": h.profile, "clean": h.clean},
    mock_dir=Path(__file__).parent.parent / "mock",
    lineage_steps=LINEAGE_STEPS,
    prompt_versions=PROMPT_VERSIONS,
    eval_fn=run_eval_subset,
)
app: FastAPI = _base


def _llm_health() -> str:
    if os.getenv("FAKE_LLM") == "1":
        return "disabled"
    try:
        from biflow_contracts.biflow_llm import _base_url

        url = f"{_base_url()}/models"
        r = httpx.get(url, timeout=2.0, headers={"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'ollama')}"})
        if r.status_code < 500:
            return "ok"
    except Exception:
        pass
    return "unreachable"


def _wrap_handler(mode: str, fn: Any) -> Any:
    budget = TIMEOUT_PROFILE_S if mode == "profile" else TIMEOUT_CLEAN_S

    def wrapped(req: RunRequest) -> RunResponse | dict:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fn, req)
            try:
                return fut.result(timeout=budget)
            except FuturesTimeout:
                raise TimeoutError(f"{mode} exceeded {budget}s budget") from None

    return wrapped


# Replace run endpoint to add timeout + domain errors (keep mock path from service_kit)
_original_run = None
for route in app.router.routes:
    if getattr(route, "path", None) == "/v1/run" and getattr(route, "methods", None) and "POST" in route.methods:
        _original_run = route.endpoint
        break

if _original_run is not None:
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/v1/run"]

    @app.post("/v1/run", response_model=RunResponse)
    def run_with_errors(req: RunRequest):
        t0 = time.perf_counter()
        module = "profile_clean"

        def done(resp: RunResponse, http: int = 200):
            resp.latency_ms = int((time.perf_counter() - t0) * 1000)
            return JSONResponse(resp.model_dump(mode="json"), status_code=http)

        def fail(code: str, msg: str, http: int) -> JSONResponse:
            return done(
                RunResponse(
                    request_id=req.request_id,
                    run_id=req.run_id,
                    module=module,
                    status="error",
                    error=ErrorInfo(code=code, message=msg),  # type: ignore[arg-type]
                ),
                http,
            )

        if req.mode not in ("profile", "clean"):
            return fail("BAD_INPUT", f"unknown mode '{req.mode}'", 400)

        if os.getenv("BIFLOW_MOCK", "1") == "1":
            return _original_run(req)

        handler = _wrap_handler(req.mode, h.profile if req.mode == "profile" else h.clean)
        try:
            out = handler(req)
            resp = out if isinstance(out, RunResponse) else RunResponse(
                request_id=req.request_id, run_id=req.run_id, module=module, **out
            )
            return done(resp)
        except BadInputError as e:
            return fail(e.code, e.message, e.http_status)
        except TimeoutError as e:
            return fail(e.code, e.message, e.http_status)
        except ProfileCleanError as e:
            return fail(e.code, e.message, e.http_status)
        except NotImplementedError:
            return fail("INTERNAL", "not implemented", 501)
        except Exception as e:
            traceback.print_exc()
            return fail("INTERNAL", f"{type(e).__name__}: {e}", 500)


app.router.routes = [
    r for r in app.router.routes if getattr(r, "path", None) not in ("/health", "/v1/meta")
]


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "module": "profile_clean",
        "mock": os.getenv("BIFLOW_MOCK", "1") == "1",
        "llm": _llm_health(),
    }


app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/v1/eval"]


@app.post("/v1/eval", response_model=EvalResponse)
def eval_override() -> EvalResponse:
    try:
        metrics = run_eval_subset()
        if metrics.get("note"):
            return EvalResponse(module="profile_clean", status="partial", notes=[metrics["note"]], metrics=metrics)
        return EvalResponse(module="profile_clean", status="ok", metrics=metrics)
    except Exception as e:
        return EvalResponse(module="profile_clean", status="partial", notes=[str(e)])


@app.get("/v1/meta", response_model=MetaResponse)
def meta_override() -> MetaResponse:
    try:
        from biflow_contracts.biflow_llm import resolve_models

        models = resolve_models()
    except Exception:
        models = {}
    return MetaResponse(
        module="profile_clean",
        contract_version=CONTRACT_VERSION,
        modes=["clean", "profile"],
        models=models,
        prompt_versions=PROMPT_VERSIONS,
        lineage_steps=LINEAGE_STEPS,
        mock=os.getenv("BIFLOW_MOCK", "1") == "1",
    )
