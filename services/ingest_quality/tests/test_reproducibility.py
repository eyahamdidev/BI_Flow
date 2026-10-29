from __future__ import annotations

import filecmp
from pathlib import Path

from app.ingest import execute_ingest
from app.quality import execute_score
from biflow_contracts import RunRequest


def test_reproducibility_identical_hashes(tmp_path: Path, monkeypatch):
    """Verify that two runs on identical input produce 100% identical hashes and metrics."""
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "test_repro"
    raw_dir.mkdir(parents=True)

    (raw_dir / "orders.csv").write_text(
        "order_id,customer_id,status,val\n"
        "O1,C1,delivered,10.5\n"
        "O2,C2,shipped,20.0\n",
        encoding="utf-8",
    )

    cfg_file = tmp_path / "ds_repro.yaml"
    cfg_file.write_text(
        f"""
name: ds_repro
source:
  type: csv
  path: {raw_dir.as_posix()}
  tables:
    orders: orders.csv
quality_score:
  weights: {{completeness: 0.5, uniqueness: 0.5, validity: 0.0, consistency: 0.0, timeliness: 0.0}}
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("DATA_DIR", str(data_dir))

    # Run 1
    req1 = RunRequest(request_id="r1", run_id="run-1", dataset="ds_repro", mode="ingest", config_ref=str(cfg_file))
    resp1_ingest = execute_ingest(req1)
    req1_score = RunRequest(request_id="s1", run_id="run-1", dataset="ds_repro", mode="score", config_ref=str(cfg_file))
    resp1_score = execute_score(req1_score)

    # Run 2
    req2 = RunRequest(request_id="r2", run_id="run-2", dataset="ds_repro", mode="ingest", config_ref=str(cfg_file))
    resp2_ingest = execute_ingest(req2)
    req2_score = RunRequest(request_id="s2", run_id="run-2", dataset="ds_repro", mode="score", config_ref=str(cfg_file))
    resp2_score = execute_score(req2_score)

    # 1. Compare parquet file hashes
    orders1_hash = next(a.sha256 for a in resp1_ingest.outputs if a.name == "orders")
    orders2_hash = next(a.sha256 for a in resp2_ingest.outputs if a.name == "orders")
    assert orders1_hash == orders2_hash, "Parquet SHA-256 hashes must be identical"

    p1 = data_dir / "runs" / "run-1" / "00_ingest" / "orders.parquet"
    p2 = data_dir / "runs" / "run-2" / "00_ingest" / "orders.parquet"
    assert filecmp.cmp(p1, p2, shallow=False)

    # 2. Compare quality scores
    assert resp1_score.metrics["overall"] == resp2_score.metrics["overall"]
    assert resp1_score.metrics["completeness"] == resp2_score.metrics["completeness"]
    assert resp1_score.metrics["uniqueness"] == resp2_score.metrics["uniqueness"]

