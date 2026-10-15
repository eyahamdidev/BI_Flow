from app import runner
from app.main import app
from fastapi.testclient import TestClient


def test_health():
    assert TestClient(app).get("/health").json()["status"] == "ok"


def test_graph_stages_reference_known_modules():
    for s in runner.load_graph():
        assert s["module"] in runner.DEFAULT_PORTS, s
        assert s["mode"] and s["name"]
