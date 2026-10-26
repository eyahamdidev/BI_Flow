"""Inject known corruptions + ground-truth manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42


def load_tables(base: Path) -> dict[str, pd.DataFrame]:
    tables = {}
    for p in base.glob("*.parquet"):
        tables[p.stem] = pd.read_parquet(p)
    return tables


def corrupt(tables: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict]:
    rng = np.random.default_rng(SEED)
    manifest: dict = {"nulls": [], "duplicates": [], "impossible": [], "spikes": []}
    out = {k: v.copy() for k, v in tables.items()}
    if "order_items" in out:
        df = out["order_items"]
        n = max(1, len(df) // 100)
        idx = rng.choice(df.index, size=n, replace=False)
        for i in idx:
            manifest["nulls"].append({"table": "order_items", "row": int(i), "column": "price"})
        df.loc[idx, "price"] = np.nan
        bad = df.index[0]
        df.loc[bad, "price"] = -1.0
        manifest["impossible"].append({"table": "order_items", "row": int(bad), "column": "price"})
        spike_i = df.index[min(5, len(df) - 1)]
        df.loc[spike_i, "freight_value"] = df["freight_value"].max() * 50
        manifest["spikes"].append({"table": "order_items", "row": int(spike_i), "column": "freight_value"})
        out["order_items"] = df
    if "geolocation" in out:
        g = out["geolocation"]
        dup = g.iloc[[0, 0]].copy()
        out["geolocation"] = pd.concat([g, dup], ignore_index=True)
        manifest["duplicates"].append({"table": "geolocation", "rows_added": 1})
    return out, manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    tables = load_tables(args.input)
    if not tables:
        raise SystemExit("no parquet in input")
    corrupted, manifest = corrupt(tables)
    for name, df in corrupted.items():
        df.to_parquet(args.output / f"{name}.parquet", index=False)
    (args.output / "ground_truth.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(corrupted)} tables to {args.output}")


if __name__ == "__main__":
    main()
