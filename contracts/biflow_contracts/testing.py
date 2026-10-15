"""Contract-test helper. Every service's tests/test_contract.py calls assert_service_contract(app)."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from .models import CONTRACT_VERSION, EvalResponse, MetaResponse, RunResponse


def assert_service_contract(app, module: str) -> None:
    c = TestClient(app)

    r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

    meta = MetaResponse(**c.get("/v1/meta").json())
    assert meta.module == module
    assert meta.contract_version == CONTRACT_VERSION
    assert meta.modes, "module must declare at least one mode"

    for mode in meta.modes:
        body = {
            "request_id": str(uuid.uuid4()), "run_id": "test-run", "dataset": "olist",
            "mode": mode, "inputs": {}, "options": {},
        }
        r = c.post("/v1/run", json=body)
        assert r.status_code == 200, f"{module}:{mode} -> {r.status_code} {r.text}"
        resp = RunResponse(**r.json())
        assert resp.module == module and resp.request_id == body["request_id"]
        assert resp.status in ("ok", "partial", "error")
        for a in resp.outputs:
            assert not a.path.startswith("/"), "artifact paths must be relative to DATA_DIR"

    bad = c.post("/v1/run", json={**body, "mode": "__nope__"})
    assert bad.status_code == 400
    assert RunResponse(**bad.json()).error.code == "BAD_INPUT"

    EvalResponse(**c.post("/v1/eval").json())
