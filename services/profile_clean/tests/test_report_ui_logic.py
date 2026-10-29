"""Report UI helpers (no full Streamlit generate flow)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from report_pdf import build, has_clean_run


def test_has_clean_run_requires_parquet(tmp_path):
    rid = "r1"
    (tmp_path / "runs" / rid / "02_clean").mkdir(parents=True)
    (tmp_path / "runs" / rid / "02_clean" / "quality_log.json").write_text("[]", encoding="utf-8")
    assert not has_clean_run(tmp_path, rid)
    pd.DataFrame({"a": [1]}).to_parquet(tmp_path / "runs" / rid / "02_clean" / "t.parquet")
    assert has_clean_run(tmp_path, rid)


def test_build_from_persisted_titanic_run():
    data = Path(__file__).resolve().parents[3] / "data"
    run_id = "upload_mydata_20261026_103233"
    if not has_clean_run(data, run_id):
        return
    pdf = build(data, run_id, "titanic", now=datetime(2026, 10, 26, 9, 0, tzinfo=UTC))
    assert pdf.is_file()
    assert pdf.stat().st_size < 5_000_000
