from biflow_contracts.testing import assert_service_contract
from mock.app.main import app


def test_mock_contract():
    assert_service_contract(app, "profile_clean")
