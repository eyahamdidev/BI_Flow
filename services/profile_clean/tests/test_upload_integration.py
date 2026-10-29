"""Full upload -> YAML -> profile -> clean chain against live service."""
from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pandas as pd
import pytest
from draft_yaml import generate_draft_yaml, yaml_dump
from playground import build_inputs, reconcile_from_disk, sha256_file
from upload_parse import csv_roundtrip_equal, read_csv_robust, write_ingest

FIX = Path(__file__).parent / "fixtures" / "uploads"
REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data"
SERVICE = "http://127.0.0.1:8103"

SINGLE_FIXTURES = [
    "01_clean_utf8.csv",
    "02_latin_semicolon.csv",
    "03_messy_headers.csv",
    "04_dirty.csv",
]
MULTI_FIXTURES = [("05_customers.csv", "05_orders.csv")]


def _service_up() -> bool:
    try:
        return httpx.get(f"{SERVICE}/health", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _service_up(), reason="service not on 8103")


def _write_yaml(cfg: dict, slug: str) -> str:
    ref = f"configs/datasets/uploaded_{slug}.yaml"
    path = REPO / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_dump(cfg), encoding="utf-8")
    return ref


def _pipeline_csvs(csv_names: list[str], run_id: str, monkeypatch, dataset_slug: str) -> dict:
    monkeypatch.setenv("DATA_DIR", str(DATA))
    tables: dict[str, pd.DataFrame] = {}
    reports = []
    for csv_name in csv_names:
        raw = (FIX / csv_name).read_bytes()
        tname = slugify_stem(csv_name)
        df, rep = read_csv_robust(raw, tname, csv_name)
        tables[tname] = df
        reports.append(rep)
    write_ingest(run_id, DATA, tables, reports, {})
    cfg = generate_draft_yaml(f"uploaded_{dataset_slug}", tables, None, llm_enabled=False)
    ref = _write_yaml(cfg, dataset_slug)
    paths = list((DATA / "runs" / run_id / "00_ingest").glob("*.parquet"))
    inputs = build_inputs(run_id, paths, base=DATA)
    body = {
        "request_id": str(uuid.uuid4()),
        "run_id": run_id,
        "dataset": cfg["name"],
        "mode": "profile",
        "config_ref": ref,
        "inputs": inputs,
        "options": {"stage": "before"},
        "lang": "en",
    }
    r1 = httpx.post(f"{SERVICE}/v1/run", json=body, timeout=180).json()
    inputs["profile"] = f"runs/{run_id}/01_profile/profile.json"
    body["mode"] = "clean"
    body["request_id"] = str(uuid.uuid4())
    body["options"] = {}
    r2 = httpx.post(f"{SERVICE}/v1/run", json=body, timeout=180).json()
    body["mode"] = "profile"
    body["request_id"] = str(uuid.uuid4())
    body["options"] = {"stage": "after", "profile_before_path": f"runs/{run_id}/01_profile/profile.json"}
    cl = DATA / "runs" / run_id / "02_clean"
    inputs_after = {
        f"clean.{p.stem}": f"runs/{run_id}/02_clean/{p.name}".replace("\\", "/")
        for p in cl.glob("*.parquet")
        if p.parent.name != "_undo"
    }
    body["inputs"] = inputs_after
    r3 = httpx.post(f"{SERVICE}/v1/run", json=body, timeout=180).json()
    return {"profile": r1, "clean": r2, "profile_after": r3, "cfg": cfg}


def slugify_stem(name: str) -> str:
    stem = Path(name).stem
    return "".join(c if c.isalnum() else "_" for c in stem).strip("_").lower() or "table"


def _assert_chain(out: dict, run_id: str, monkeypatch) -> None:
    assert out["profile"]["status"] in ("ok", "partial")
    assert out["clean"]["status"] in ("ok", "partial"), out["clean"].get("error")
    assert out["profile_after"]["status"] in ("ok", "partial")
    assert out["clean"]["metrics"].get("silent_deletions", 0) == 0
    for a in out["clean"].get("outputs", []):
        if a.get("sha256") and a.get("kind") == "parquet":
            fp = DATA / a["path"]
            assert fp.exists()
            assert sha256_file(fp) == a["sha256"]
    monkeypatch.setenv("DATA_DIR", str(DATA))
    recon = reconcile_from_disk(run_id)
    assert all(x[1] for x in recon if x[0].startswith("Reconcile"))
    undo_dir = DATA / "runs" / run_id / "02_clean" / "_undo"
    if undo_dir.is_dir():
        ufiles = list(undo_dir.glob("*.parquet"))
        if ufiles:
            undo = pd.read_parquet(ufiles[0])
            assert "original_value" in undo.columns
    clean_dir = DATA / "runs" / run_id / "02_clean"
    for pq in clean_dir.glob("*.parquet"):
        df = pd.read_parquet(pq)
        assert csv_roundtrip_equal(df)


@pytest.mark.parametrize("csv", SINGLE_FIXTURES)
def test_upload_chain_single(monkeypatch, csv):
    slug = csv.replace(".", "_")
    rid = f"up_{uuid.uuid4().hex[:8]}_{slug}"
    out = _pipeline_csvs([csv], rid, monkeypatch, slug)
    _assert_chain(out, rid, monkeypatch)


def test_upload_chain_multi_table(monkeypatch):
    slug = "05_parent_child"
    rid = f"up_{uuid.uuid4().hex[:8]}_{slug}"
    out = _pipeline_csvs(["05_customers.csv", "05_orders.csv"], rid, monkeypatch, slug)
    _assert_chain(out, rid, monkeypatch)
    rels = out["cfg"].get("relationships", [])
    assert rels, "expected FK suggestion between uploaded tables"


def test_empty_file_no_crash():
    with pytest.raises(ValueError):
        read_csv_robust((FIX / "07_empty.csv").read_bytes(), "x", "07_empty.csv")


def test_header_only_no_crash():
    with pytest.raises(ValueError):
        read_csv_robust((FIX / "07_header_only.csv").read_bytes(), "x", "07_header_only.csv")


@pytest.mark.slow
def test_large_file_benchmark(monkeypatch):
    large = FIX / "06_large.csv"
    if not large.is_file():
        pytest.skip("Run tests/make_messy_uploads.py --large to generate 06_large.csv")
    import time

    rid = f"up_large_{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()
    out = _pipeline_csvs(["06_large.csv"], rid, monkeypatch, "06_large")
    elapsed = time.perf_counter() - t0
    _assert_chain(out, rid, monkeypatch)
    assert elapsed < 240, f"pipeline took {elapsed:.1f}s (budget ~180s profile+clean)"
