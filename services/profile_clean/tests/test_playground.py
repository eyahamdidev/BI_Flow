"""Headless Streamlit AppTest for playground.py (skips if service down)."""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

pytest.importorskip("streamlit.testing.v1")

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
PLAYGROUND = ROOT / "playground.py"
SERVICE = os.getenv("PLAYGROUND_SERVICE_URL", "http://127.0.0.1:8103")


def _service_up() -> bool:
    try:
        r = httpx.get(f"{SERVICE}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


service_required = pytest.mark.skipif(not _service_up(), reason="profile_clean not reachable on 8103")


@service_required
def test_playground_loads_and_buttons():
    os.environ["DATA_DIR"] = str(REPO / "data")
    at = AppTest.from_file(str(PLAYGROUND))
    at.run(timeout=60)
    assert not at.exception

    def click_button(substr: str, timeout: int = 120) -> None:
        for i, b in enumerate(at.button):
            if substr in (b.label or ""):
                at.button[i].click().run(timeout=timeout)
                return
        raise AssertionError(f"button not found: {substr}")

    click_button("olist_mini fixture", timeout=60)
    assert not at.exception
    for label_part in ("Profile (before)", "Clean"):
        click_button(label_part, timeout=120)
        assert not at.exception
    at.run(timeout=30)
    for i, b in enumerate(at.button):
        if "Profile (after)" in (b.label or ""):
            if not getattr(b, "disabled", False):
                at.button[i].click().run(timeout=120)
                assert not at.exception
            break
    # Edge case: unknown mode
    at.run(timeout=30)
    for i, b in enumerate(at.button):
        if "Unknown mode" in b.label:
            at.button[i].click().run(timeout=30)
            assert not at.exception
            break
