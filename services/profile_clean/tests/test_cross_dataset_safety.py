"""Cross-dataset safety: roles, guards, invariants, Titanic/Iris ground truth."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx
import pandas as pd
import pytest
import yaml
from app.column_roles import infer_column_role
from app.handlers import clean, profile
from app.invariants import check_cleaning_invariants
from biflow_contracts import RunRequest
from draft_yaml import generate_draft_yaml, yaml_dump
from upload_parse import read_csv_robust, write_ingest

FIX = Path(__file__).parent / "fixtures" / "datasets"
REPO = Path(__file__).resolve().parents[3]
SERVICE = "http://127.0.0.1:8103"


@pytest.fixture(scope="module", autouse=True)
def _ensure_fixtures():
    if not (FIX / "titanic.csv").is_file():
        import subprocess
        import sys

        subprocess.run([sys.executable, str(FIX / "make_datasets.py")], check=True)


def _service_up() -> bool:
    try:
        return httpx.get(f"{SERVICE}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _run_clean_local(monkeypatch, tmp_path, csv_path: Path, table: str, dataset: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    os.environ["DATA_DIR"] = str(tmp_path)
    os.environ["FAKE_LLM"] = "1"
    raw = csv_path.read_bytes()
    df, rep = read_csv_robust(raw, table, csv_path.name)
    run_id = f"safe_{uuid.uuid4().hex[:8]}"
    write_ingest(run_id, tmp_path, {table: df}, [rep], {})
    cfg = generate_draft_yaml(f"uploaded_{dataset}", {table: df}, None, llm_enabled=False)
    ref = tmp_path / "cfg.yaml"
    ref.write_text(yaml_dump(cfg), encoding="utf-8")
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
    assert resp["status"] in ("ok", "partial"), resp.get("error")
    assert resp["metrics"]["silent_deletions"] == 0
    raw_df = pd.read_parquet(tmp_path / "runs" / run_id / "00_ingest" / f"{table}.parquet")
    clean_df = pd.read_parquet(tmp_path / "runs" / run_id / "02_clean" / f"{table}.parquet")
    return raw_df, clean_df, resp


def test_titanic_ground_truth(monkeypatch, tmp_path):
    raw_df, clean_df, resp = _run_clean_local(monkeypatch, tmp_path, FIX / "titanic.csv", "titanic", "titanic")
    assert len(clean_df) == 891
    assert clean_df["PassengerId"].equals(raw_df["PassengerId"])
    assert pd.api.types.is_string_dtype(clean_df["Ticket"]) or clean_df["Ticket"].dtype == object
    assert "Ticket__imputed" not in clean_df.columns
    assert "Ticket__outlier" not in clean_df.columns
    assert "Pclass__outlier" not in clean_df.columns
    assert "Survived__outlier" not in clean_df.columns
    assert str(clean_df["Survived"].dtype) in ("Int64", "int64", "int32")
    assert int(clean_df["Age__imputed"].sum()) == int(raw_df["Age"].isna().sum())
    assert clean_df["Cabin"].isna().sum() == raw_df["Cabin"].isna().sum()
    assert "Cabin__high_null" in clean_df.columns or "Cabin_high_null_flag" in clean_df.columns
    assert int(clean_df["Embarked__imputed"].sum()) == int(raw_df["Embarked"].isna().sum())
    assert int(clean_df["Fare__outlier"].sum()) > 0
    v = check_cleaning_invariants(raw_df, clean_df, pk_col="PassengerId", rows_dropped=0)
    assert not v, v


def test_iris_outliers_and_dup(monkeypatch, tmp_path):
    raw_df, clean_df, resp = _run_clean_local(monkeypatch, tmp_path, FIX / "iris.csv", "iris", "iris")
    assert len(clean_df) == 149
    flagged = sum(int(clean_df[c].sum()) for c in clean_df.columns if c.endswith("__outlier"))
    assert resp["metrics"]["outliers_flagged"] == flagged
    assert flagged >= 4
    sw = pd.to_numeric(raw_df["sepal.width"], errors="coerce")
    q1, q3 = sw.quantile(0.25), sw.quantile(0.75)
    iqr = q3 - q1
    expected = int((sw.notna() & ((sw < q1 - 1.5 * iqr) | (sw > q3 + 1.5 * iqr))).sum())
    assert int(clean_df["sepal.width__outlier"].sum()) >= min(4, expected)


def test_type_guard_blocks_unsafe_yaml(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    os.environ["FAKE_LLM"] = "1"
    df = pd.DataFrame({"id": ["a", "b"], "label": ["x", "y"]})
    run_id = "guard"
    dest = tmp_path / "runs" / run_id / "00_ingest"
    dest.mkdir(parents=True)
    df.to_parquet(dest / "main.parquet")
    cfg = {
        "name": "guard",
        "expected_schema": {"main": {"id": {"dtype": "str", "role": "id"}, "label": {"dtype": "str", "role": "id"}}},
        "cleaning_rules": {
            "primary_keys": {"main": "id"},
            "null_strategy": {
                "main.label": {"strategy": "median", "imputed_flag": "label__imputed"},
            },
            "outliers": {"method": "iqr", "columns": ["main.id"], "action": "flag"},
            "llm_advisory": {"enabled": False},
        },
    }
    ref = tmp_path / "bad.yaml"
    ref.write_text(yaml.dump(cfg), encoding="utf-8")
    inputs = {"ingest.main": f"runs/{run_id}/00_ingest/main.parquet"}
    clean(
        RunRequest(
            request_id=str(uuid.uuid4()),
            run_id=run_id,
            dataset="guard",
            mode="clean",
            config_ref=str(ref),
            inputs=inputs,
        )
    )
    rq = json.loads((tmp_path / "runs" / run_id / "02_clean" / "review_queue.json").read_text(encoding="utf-8"))
    assert any("type-safety guard" in str(x.get("reason", "")) for x in rq)
    assert "label__imputed" not in pd.read_parquet(tmp_path / "runs" / run_id / "02_clean" / "main.parquet").columns


def test_role_ticket_is_id():
    s = pd.Series(["A/5 21171", "349222", "PC 17599"])
    info = infer_column_role("Ticket", s)
    assert info.role == "id"


def test_role_pclass_categorical():
    s = pd.Series([1, 2, 3, 1, 2, 3] * 10)
    info = infer_column_role("Pclass", s)
    assert info.role == "categorical"


@pytest.mark.parametrize(
    "csv,table",
    [
        ("titanic.csv", "titanic"),
        ("iris.csv", "iris"),
        ("cafe_dirty.csv", "cafe"),
        ("hotel_dirty.csv", "hotel"),
    ],
)
def test_invariants_parametric(monkeypatch, tmp_path, csv, table):
    raw_df, clean_df, _ = _run_clean_local(monkeypatch, tmp_path, FIX / csv, table, table)
    pk = raw_df.columns[0]
    dropped = len(raw_df) - len(clean_df)
    v = check_cleaning_invariants(raw_df, clean_df, pk_col=pk, rows_dropped=dropped)
    assert not v, v


@pytest.mark.skipif(not _service_up(), reason="service not on 8103")
def test_http_titanic_smoke(monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(REPO / "data"))
    raw = (FIX / "titanic.csv").read_bytes()
    df, rep = read_csv_robust(raw, "titanic", "titanic.csv")
    run_id = f"http_titanic_{uuid.uuid4().hex[:6]}"
    write_ingest(run_id, REPO / "data", {"titanic": df}, [rep], {})
    cfg = generate_draft_yaml("uploaded_titanic", {"titanic": df}, None)
    ref = "configs/datasets/uploaded_titanic_http.yaml"
    (REPO / ref).parent.mkdir(parents=True, exist_ok=True)
    (REPO / ref).write_text(yaml_dump(cfg), encoding="utf-8")
    inputs = {"ingest.titanic": f"runs/{run_id}/00_ingest/titanic.parquet"}
    body = {
        "request_id": str(uuid.uuid4()),
        "run_id": run_id,
        "dataset": cfg["name"],
        "mode": "clean",
        "config_ref": ref,
        "inputs": inputs,
        "options": {},
    }
    r = httpx.post(f"{SERVICE}/v1/run", json=body, timeout=120).json()
    assert r["status"] in ("ok", "partial")
    assert r["metrics"]["silent_deletions"] == 0
