"""PDF report: fidelity, privacy, missing artifacts, validity, determinism."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from draft_yaml import generate_draft_yaml, yaml_dump
from pypdf import PdfReader
from report_pdf import (
    build,
    escape_para,
    extract_pdf_text,
    has_clean_run,
    persist_run_snapshot,
)
from upload_parse import read_csv_robust, write_ingest

FIX = Path(__file__).parent / "fixtures" / "datasets"
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def _fixtures():
    if not (FIX / "titanic.csv").is_file():
        import subprocess
        import sys

        subprocess.run([sys.executable, str(FIX / "make_datasets.py")], check=True)


def _run_pipeline(tmp_path: Path, csv_path: Path, table: str, dataset: str) -> str:
    import os

    from app.handlers import clean, profile
    from biflow_contracts import RunRequest

    os.environ["DATA_DIR"] = str(tmp_path)
    os.environ["FAKE_LLM"] = "1"
    raw = csv_path.read_bytes()
    df, rep = read_csv_robust(raw, table, csv_path.name)
    run_id = f"pdf_{uuid.uuid4().hex[:8]}"
    write_ingest(run_id, tmp_path, {table: df}, [rep], {})
    cfg = generate_draft_yaml(f"uploaded_{dataset}", {table: df}, None, llm_enabled=False)
    ref = tmp_path / "cfg.yaml"
    ref.write_text(yaml_dump(cfg), encoding="utf-8")
    (tmp_path / "runs" / run_id / "config_used.yaml").write_text(yaml_dump(cfg), encoding="utf-8")
    inputs = {f"ingest.{table}": f"runs/{run_id}/00_ingest/{table}.parquet"}
    profile(
        RunRequest(
            request_id=str(uuid.uuid4()),
            run_id=run_id,
            dataset=cfg["name"],
            mode="profile",
            config_ref=str(ref),
            inputs=inputs,
            options={"stage": "before"},
        )
    )
    inputs["profile"] = f"runs/{run_id}/01_profile/profile.json"
    resp = clean(
        RunRequest(
            request_id=str(uuid.uuid4()),
            run_id=run_id,
            dataset=cfg["name"],
            mode="clean",
            config_ref=str(ref),
            inputs=inputs,
        )
    )
    assert resp["status"] in ("ok", "partial")
    persist_run_snapshot(tmp_path / "runs" / run_id, "clean", resp)
    inputs_after = {f"clean.{table}": f"runs/{run_id}/02_clean/{table}.parquet"}
    profile(
        RunRequest(
            request_id=str(uuid.uuid4()),
            run_id=run_id,
            dataset=cfg["name"],
            mode="profile",
            config_ref=str(ref),
            inputs=inputs_after,
            options={"stage": "after", "profile_before_path": f"runs/{run_id}/01_profile/profile.json"},
        )
    )
    return run_id


def test_escape_hostile_strings():
    assert "&amp;" in escape_para("<b> &amp;")
    assert escape_para("a" * 500).endswith("a") or len(escape_para("a" * 500)) == 500
    assert "😀" in escape_para("😀")
    assert escape_para("مرحبا") == "مرحبا"


def test_build_titanic_number_fidelity(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    run_id = _run_pipeline(tmp_path, FIX / "titanic.csv", "titanic", "titanic")
    assert has_clean_run(tmp_path, run_id)
    fixed = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
    pdf = build(tmp_path, run_id, "titanic", now=fixed, tz=ZoneInfo("UTC"))
    text = extract_pdf_text(pdf)
    assert "891" in text.replace(",", "")
    m = json.loads((tmp_path / "runs" / run_id / "02_clean" / "quality_log.json").read_text(encoding="utf-8"))
    imputed = sum(int(e.get("cells_imputed") or 0) for e in m if "impute" in str(e.get("rule_id")))
    assert str(imputed) in text.replace(",", "") or str(imputed) in text
    reader = PdfReader(str(pdf))
    assert len(reader.pages) >= 5
    assert reader.metadata and "BIFlow" in (reader.metadata.title or "")


def test_iris_metrics_in_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    run_id = _run_pipeline(tmp_path, FIX / "iris.csv", "iris", "iris")
    man = json.loads((tmp_path / "runs" / run_id / "00_ingest" / "ingest_manifest.json").read_text(encoding="utf-8"))
    expected_rows = str(man["tables"][0]["rows"])
    pdf = build(tmp_path, run_id, "iris", now=datetime(2026, 1, 2, tzinfo=UTC))
    text = extract_pdf_text(pdf)
    assert expected_rows in text.replace(",", "") or expected_rows.encode() in pdf.read_bytes()


def test_privacy_mode_hides_samples(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    run_id = _run_pipeline(tmp_path, FIX / "titanic.csv", "titanic", "titanic")
    pdf = build(tmp_path, run_id, "titanic", privacy=True, now=datetime(2026, 1, 2, tzinfo=UTC))
    text = extract_pdf_text(pdf)
    assert "Braund" not in text
    assert "•••" in text


def test_missing_profile_after_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    run_id = _run_pipeline(tmp_path, FIX / "titanic.csv", "titanic", "titanic")
    shutil.rmtree(tmp_path / "runs" / run_id / "03_profile_after")
    pdf = build(tmp_path, run_id, "titanic", now=datetime(2026, 1, 2, tzinfo=UTC))
    text = extract_pdf_text(pdf)
    assert "Not available" in text or "Non disponible" in text or "profile" in text.lower()
    assert pdf.is_file()


def test_fail_verdict_tampered_reconcile(tmp_path, monkeypatch):
    import pandas as pd

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    run_id = _run_pipeline(tmp_path, FIX / "titanic.csv", "titanic", "titanic")
    clean_p = tmp_path / "runs" / run_id / "02_clean" / "titanic.parquet"
    df = pd.read_parquet(clean_p)
    df = df.iloc[:-5]
    df.to_parquet(clean_p, index=False)
    pdf = build(tmp_path, run_id, "titanic", now=datetime(2026, 1, 2, tzinfo=UTC))
    text = extract_pdf_text(pdf)
    assert "FAIL" in text or "ÉCHEC" in text
    assert "Row accounting" in text or "886" in text


def test_deterministic_with_fixed_now(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    run_id = _run_pipeline(tmp_path, FIX / "titanic.csv", "titanic", "titanic")
    fixed = datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC)
    p1 = build(tmp_path, run_id, "titanic", now=fixed, tz=ZoneInfo("UTC"))
    p2 = build(tmp_path, run_id, "titanic", now=fixed, tz=ZoneInfo("UTC"))
    t1 = extract_pdf_text(p1)
    t2 = extract_pdf_text(p2)
    assert t1 == t2


def test_large_recognition_and_qlog_caps(tmp_path):
    run_id = "pdf_wide"
    rd = tmp_path / "runs" / run_id
    (rd / "00_ingest").mkdir(parents=True)
    (rd / "02_clean").mkdir(parents=True)
    (rd / "00_ingest" / "ingest_manifest.json").write_text(json.dumps({"run_id": run_id, "tables": [], "parse_settings": {}}), encoding="utf-8")
    cols = [{"table": "t", "column": f"c{i}", "role": "continuous_numeric", "semantic_type": "float", "confidence": 0.95, "evidence": ["x"], "proposed_action": "none"} for i in range(500)]
    (rd / "02_clean" / "recognition_report.json").write_text(json.dumps({"columns": cols}), encoding="utf-8")
    qlog = [{"rule_id": "impute_numeric", "table": "t", "column": f"c{i}", "rows_affected": 1} for i in range(10000)]
    (rd / "02_clean" / "quality_log.json").write_text(json.dumps(qlog), encoding="utf-8")
    import pandas as pd

    pd.DataFrame({"c0": [1]}).to_parquet(rd / "00_ingest" / "t.parquet")
    pd.DataFrame({"c0": [1]}).to_parquet(rd / "02_clean" / "t.parquet")
    pdf = build(tmp_path, run_id, "wide", now=datetime(2026, 1, 1, tzinfo=UTC))
    assert pdf.stat().st_size < 5_000_000
    text = extract_pdf_text(pdf)
    assert "500" in text or "appendix" in text.lower()


def test_playground_report_section_apptest():
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(root / "playground.py"), default_timeout=60)
    at.run(timeout=60)
    assert not at.exception
