"""Tiny FastAPI factory so every module exposes the SAME four endpoints, error format and mock switch.

Module owners implement handlers: {mode: fn(req: RunRequest) -> RunResponse | dict}
and (optionally) an eval function. Everything else is uniform.

Mock mode (default in the skeleton): BIFLOW_MOCK=1 returns mock/<mode>.json fixtures for the
real endpoints, so the orchestrator can build against it from day one.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .models import (
    CONTRACT_VERSION,
    ErrorInfo,
    EvalResponse,
    MetaResponse,
    RunRequest,
    RunResponse,
)

Handler = Callable[[RunRequest], "RunResponse | dict[str, Any]"]


def _is_mock(module: str) -> bool:
    """BIFLOW_MOCK_<MODULE> (e.g. BIFLOW_MOCK_ETL=0) wins over the global BIFLOW_MOCK, so modules go real one at a time."""
    # an EMPTY per-module value counts as unset (falls back to the global switch)
    return (os.getenv(f"BIFLOW_MOCK_{module.upper()}") or os.getenv("BIFLOW_MOCK", "1")) == "1"


def create_app(
    module: str,
    handlers: dict[str, Handler],
    mock_dir: str | Path,
    lineage_steps: list[str] | None = None,
    prompt_versions: dict[str, str] | None = None,
    eval_fn: Callable[[], dict[str, Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title=f"BIFlow / {module}", version=CONTRACT_VERSION)
    mock_dir = Path(mock_dir)

    def _models() -> dict[str, str]:
        # Imported lazily so services without LLM needs never touch it.
        try:
            from .biflow_llm import resolve_models

            return resolve_models()
        except Exception:  # noqa: BLE001
            return {}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "module": module, "mock": _is_mock(module)}

    @app.get("/v1/meta", response_model=MetaResponse)
    def meta() -> MetaResponse:
        return MetaResponse(
            module=module,
            modes=sorted(handlers),
            models=_models(),
            prompt_versions=prompt_versions or {},
            lineage_steps=lineage_steps or [],
            mock=_is_mock(module),
        )

    @app.post("/v1/run", response_model=RunResponse)
    def run(req: RunRequest):
        t0 = time.perf_counter()

        def done(resp: RunResponse, http: int = 200):
            resp.latency_ms = int((time.perf_counter() - t0) * 1000)
            return JSONResponse(resp.model_dump(mode="json"), status_code=http)

        def fail(code: str, msg: str, http: int) -> JSONResponse:
            return done(
                RunResponse(
                    request_id=req.request_id, run_id=req.run_id, module=module, status="error",
                    error=ErrorInfo(code=code, message=msg),  # type: ignore[arg-type]
                ),
                http,
            )

        if req.mode not in handlers:
            return fail("BAD_INPUT", f"unknown mode '{req.mode}'; supported: {sorted(handlers)}", 400)

        try:
            if _is_mock(module):
                fx = mock_dir / f"{req.mode}.json"
                if not fx.exists():
                    return fail("INTERNAL", f"mock fixture missing: {fx.name}", 500)
                data = json.loads(fx.read_text(encoding="utf-8"))
                data.update(request_id=req.request_id, run_id=req.run_id, module=module)
                # Fixture paths use {run_id} so mocks look like real run outputs.
                data = json.loads(json.dumps(data).replace("{run_id}", req.run_id))
                return done(RunResponse(**data))

            out = handlers[req.mode](req)
            resp = out if isinstance(out, RunResponse) else RunResponse(
                request_id=req.request_id, run_id=req.run_id, module=module, **out
            )
            return done(resp)
        except NotImplementedError:
            return fail("INTERNAL", f"mode '{req.mode}' is not implemented yet (set BIFLOW_MOCK=1 to use the mock)", 501)
        except Exception as e:  # noqa: BLE001  a module must degrade, not crash
            traceback.print_exc()
            return fail("INTERNAL", f"{type(e).__name__}: {e}", 500)

    @app.post("/v1/eval", response_model=EvalResponse)
    def run_eval() -> EvalResponse:
        if _is_mock(module) or eval_fn is None:
            return EvalResponse(module=module, status="partial", notes=["no eval implemented yet"])
        return EvalResponse(module=module, status="ok", metrics=eval_fn())

    return app
