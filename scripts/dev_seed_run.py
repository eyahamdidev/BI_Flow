"""DEV ONLY: stand-in for BO4's ingest until it is real.

Reads a dataset's CSVs and writes data/runs/<run_id>/00_ingest/<table>.parquet, the same layout the real
ingest service produces, so downstream modules (clean, etl, ...) can be developed on real data today.

    python scripts/dev_seed_run.py --dataset olist --source tests/fixtures/olist_sample --run-id dev-sample
    python scripts/dev_seed_run.py --dataset olist --source data/raw/olist --run-id dev-full

Typing (like a plain CSV ingest): columns declared `str` in expected_schema stay text (zip codes keep leading zeros);
any other column whose values are all numeric becomes a number; everything else stays text.
Dates stay text: parsing them is the cleaner's job.
Prints the `inputs` map to pass to the next stage ({"ingest.<table>": "runs/<id>/00_ingest/<table>.parquet"}).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent


def seed(dataset: str, source: str | None, run_id: str, data_dir: Path) -> dict[str, str]:
    """Write <data_dir>/runs/<run_id>/00_ingest/<table>.parquet. Returns the inputs map for the next stage."""
    cfg = yaml.safe_load((ROOT / "configs" / "datasets" / f"{dataset}.yaml").read_text(encoding="utf-8"))
    src = ROOT / (source or cfg["source"]["path"])
    out = data_dir / "runs" / run_id / "00_ingest"
    out.mkdir(parents=True, exist_ok=True)

    inputs = {}
    for table, fname in cfg["source"]["tables"].items():
        df = pd.read_csv(src / fname, dtype=str, keep_default_na=False)
        df = df.replace("", None)  # empty cell = missing value
        schema = cfg.get("expected_schema", {}).get(table) or {}
        keep_text = {c for c, spec in schema.items() if (spec["type"] if isinstance(spec, dict) else spec) == "str"}
        for col in df.columns:
            if col in keep_text:
                continue
            try:
                df[col] = pd.to_numeric(df[col])  # int64 if whole numbers without gaps, else float64
            except (ValueError, TypeError):
                pass  # not numeric: stays text
        df.to_parquet(out / f"{table}.parquet", index=False)
        inputs[f"ingest.{table}"] = f"runs/{run_id}/00_ingest/{table}.parquet"
        print(f"  {table:<22} {len(df):>8} rows -> {out / (table + '.parquet')}")
    (out / "inputs.json").write_text(json.dumps(inputs, indent=2))
    print(f"inputs map written to {out / 'inputs.json'}")
    return inputs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="olist")
    ap.add_argument("--source", help="folder with the CSVs (default: source.path from the dataset YAML)")
    ap.add_argument("--run-id", default="dev-sample")
    a = ap.parse_args()
    seed(a.dataset, a.source, a.run_id, Path(os.getenv("DATA_DIR", ROOT / "data")))


if __name__ == "__main__":
    main()
