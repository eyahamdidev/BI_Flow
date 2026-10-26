"""Generate sample PDFs + PNG previews for visual QA."""
from __future__ import annotations

import io
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPO = ROOT.parents[1]
OUT = ROOT / "eval" / "report_samples"


def _pipeline(data_dir: Path, csv_path: Path, table: str, dataset: str) -> tuple[str, float]:
    import os

    import yaml
    from app.handlers import clean, profile
    from biflow_contracts import RunRequest
    from draft_yaml import generate_draft_yaml, yaml_dump
    from report_pdf import build, persist_run_snapshot
    from upload_parse import read_csv_robust, write_ingest

    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["FAKE_LLM"] = "1"
    t0 = time.perf_counter()
    raw = csv_path.read_bytes()
    df, rep = read_csv_robust(raw, table, csv_path.name)
    run_id = f"sample_{dataset}_{uuid.uuid4().hex[:6]}"
    write_ingest(run_id, data_dir, {table: df}, [rep], {})
    cfg = generate_draft_yaml(f"uploaded_{dataset}", {table: df}, None, llm_enabled=False)
    ref = data_dir / f"cfg_{dataset}.yaml"
    ref.write_text(yaml_dump(cfg), encoding="utf-8")
    (data_dir / "runs" / run_id / "config_used.yaml").write_text(yaml_dump(cfg), encoding="utf-8")
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
    persist_run_snapshot(data_dir / "runs" / run_id, "clean", resp)
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
    fixed = datetime(2026, 10, 26, 9, 0, 0, tzinfo=timezone.utc)
    pdf = build(data_dir, run_id, dataset, now=fixed, tz=ZoneInfo("UTC"))
    elapsed = time.perf_counter() - t0
    return str(pdf), elapsed


def _render_pngs(pdf_path: Path, dest: Path) -> None:
    import pypdfium2 as pdfium

    dest.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    for i in range(len(pdf)):
        page = pdf[i]
        pil = page.render(scale=2.0).to_pil()
        pil.save(dest / f"page_{i + 1:02d}.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fix = ROOT / "tests" / "fixtures" / "datasets"
    messy = REPO / "data" / "runs" / "up_97d9f0b8_04_dirty_csv"
    timings: list[tuple[str, float]] = []

    for label, csv_path, table, dataset in [
        ("titanic", fix / "titanic.csv", "titanic", "titanic"),
        ("iris", fix / "iris.csv", "iris", "iris"),
    ]:
        pdf, sec = _pipeline(REPO / "data", csv_path, table, dataset)
        p = Path(pdf)
        target = OUT / f"{label}.pdf"
        shutil.copy2(p, target)
        _render_pngs(target, OUT / label)
        timings.append((label, sec))
        print(label, target, f"{sec:.1f}s")

    if messy.is_dir():
        from report_pdf import build

        run_id = messy.name
        pdf = build(REPO / "data", run_id, "04_dirty", now=datetime(2026, 10, 26, 9, 0, 0, tzinfo=timezone.utc))
        target = OUT / "messy_dirty_csv.pdf"
        shutil.copy2(pdf, target)
        _render_pngs(target, OUT / "messy")
        print("messy", target)

    (OUT / "timings.txt").write_text("\n".join(f"{k}: {v:.2f}s" for k, v in timings), encoding="utf-8")


if __name__ == "__main__":
    main()
