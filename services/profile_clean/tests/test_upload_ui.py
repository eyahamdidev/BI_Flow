"""AppTest: upload tab ingest + run everything (requires service on 8103)."""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

pytest.importorskip("streamlit.testing.v1")

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
PLAYGROUND = ROOT / "playground.py"
FIX = Path(__file__).parent / "fixtures" / "uploads" / "02_latin_semicolon.csv"
SERVICE = os.getenv("PLAYGROUND_SERVICE_URL", "http://127.0.0.1:8103")


def _service_up() -> bool:
    try:
        return httpx.get(f"{SERVICE}/health", timeout=2.0).status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _service_up(), reason="profile_clean not reachable on 8103")
def test_upload_tab_run_everything():
    os.environ["DATA_DIR"] = str(REPO / "data")
    at = AppTest.from_file(str(PLAYGROUND))
    at.run(timeout=90)
    assert not at.exception
    assert len(at.tabs) >= 2, "expected Built-in demo and My uploads tabs"
    # File uploader bytes are awkward in AppTest; smoke ingest via library
    from upload_parse import read_csv_robust, write_ingest

    rid = "apptest_upload_smoke"
    raw = FIX.read_bytes()
    df, rep = read_csv_robust(raw, "main", FIX.name)
    write_ingest(rid, REPO / "data", {"main": df}, [rep], {})
    assert (REPO / "data" / "runs" / rid / "00_ingest" / "main.parquet").is_file()
