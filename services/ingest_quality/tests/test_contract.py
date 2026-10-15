from app.main import app
from biflow_contracts.testing import assert_service_contract


def test_contract():
    assert_service_contract(app, "ingest_quality")
