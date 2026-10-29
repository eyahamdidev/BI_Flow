"""Contract tests validating all service mocks and contract definitions (owned by BO4).

Spec section 1, rule 11:
"Contract tests run in CI (pytest + jsonschema) against each module's mock and,
when available, its real service. A red contract test blocks merge."
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from biflow_contracts.models import RunResponse

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
SERVICES_DIR = ROOT / "services"

SERVICES = [
    "ingest_quality",
    "profile_clean",
    "etl",
    "semantic_kpi",
    "analyst",
    "auditor",
]


def _get_mock_cases():
    cases = []
    for s in SERVICES:
        m_dir = SERVICES_DIR / s / "mock"
        if m_dir.exists():
            for f in sorted(m_dir.glob("*.json")):
                cases.append(pytest.param(s, f, id=f"{s}_{f.stem}"))
    return cases


@pytest.fixture(scope="session")
def run_response_schema():
    schema_path = SCHEMAS_DIR / "RunResponse.json"
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("service,mock_file", _get_mock_cases())
def test_mock_validates_against_contract_schema(service: str, mock_file: Path, run_response_schema: dict):
    raw_content = mock_file.read_text(encoding="utf-8")
    rendered_content = raw_content.replace("{run_id}", "test-contract-run")
    data = json.loads(rendered_content)

    data.setdefault("request_id", "req-test-contract")
    data.setdefault("run_id", "test-contract-run")
    data.setdefault("module", service)

    # 1. Validate against Pydantic v2 Contract model
    response_model = RunResponse(**data)
    assert response_model.module == service
    assert response_model.status in ("ok", "partial", "error")

    # 2. Validate against JSONSchema
    jsonschema.validate(instance=data, schema=run_response_schema)
