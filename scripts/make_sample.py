"""Build a small, FK-consistent sample of a dataset for tests and fast dev runs.

    python scripts/make_sample.py --dataset olist --frac 0.01 --seed 42
    # in Docker (no local pandas needed):
    docker compose run --rm --no-deps -v "$PWD:/repo" -w /repo etl python scripts/make_sample.py --dataset olist

How it works (driven by configs/datasets/<name>.yaml, no dataset-specific code):
  1. Sample `frac` of the ROOT table (e.g. orders) with a fixed seed -> same sample every time.
     Top up so every value of the `cover` columns appears at least `min_per_value` times (rare statuses).
  2. CHILD tables (they reference a kept table, e.g. order_items -> orders) keep rows whose FK points to kept rows.
  3. PARENT tables (referenced by kept tables, e.g. products <- order_items) keep only the referenced rows,
     once every table that references them is settled.
  4. `keep_full` tables are copied whole; `extra_links` are soft links (geolocation by zip prefix);
     `max_rows_per_key` caps tables with many rows per key (geolocation).

Raw values are copied EXACTLY: every column is read as text, empty cells stay empty (no NaN, zip "01037" keeps its 0).
The sample must stay as messy as the original, because the profiler and cleaner are tested on it.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _split(ref: str) -> tuple[str, str]:
    table, col = ref.split(".", 1)
    return table, col


def read_table(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)


def sample_root(df: pd.DataFrame, frac: float, seed: int, cover: list[str], min_per_value: int) -> pd.DataFrame:
    picked = df.sample(frac=frac, random_state=seed)
    extra = []
    for col in cover:
        for value, group in df.groupby(col):
            missing = min_per_value - int((picked[col] == value).sum())
            if missing > 0:
                pool = group.drop(picked.index, errors="ignore")
                extra.append(pool.sample(n=min(missing, len(pool)), random_state=seed))
    return pd.concat([picked, *extra]).sort_index()


def build_sample(cfg: dict, frac: float, seed: int) -> dict[str, pd.DataFrame]:
    src = ROOT / cfg["source"]["path"]
    s = cfg["sample"]
    full = {t: read_table(src / f) for t, f in cfg["source"]["tables"].items()}

    # links: (child_table, child_col, parent_table, parent_col)
    links = [(*_split(r["from"]), *_split(r["to"])) for r in cfg.get("relationships", []) + s.get("extra_links", [])]

    root_t = s["root"]["table"]
    kept = {root_t: sample_root(full[root_t], frac, seed, s.get("cover", []), s.get("min_per_value", 1))}
    core = {root_t}  # root + its children: filtered by the keys of what they point to
    for t in s.get("keep_full", []):
        kept[t] = full[t]

    changed = True
    while changed:
        changed = False
        for child, ccol, parent, pcol in links:
            # step 2: child of a core table -> keep rows pointing at kept parent rows
            if parent in core and child not in kept:
                kept[child] = full[child][full[child][ccol].isin(kept[parent][pcol])]
                core.add(child)
                changed = True
        for parent in {p for _, _, p, _ in links} - kept.keys():
            refs = [(c, cc) for c, cc, p, _ in links if p == parent]
            if all(c in kept for c, _ in refs):  # step 3: wait until every referencing table is settled
                pcol = next(pc for _, _, p, pc in links if p == parent)
                wanted = pd.concat([kept[c][cc] for c, cc in refs]).unique()
                rows = full[parent][full[parent][pcol].isin(wanted)]
                cap = s.get("max_rows_per_key", {}).get(parent)
                kept[parent] = rows.groupby(pcol, sort=False).head(cap) if cap else rows
                changed = True

    missing = set(full) - kept.keys()
    if missing:
        raise SystemExit(f"tables not reachable from the root via relationships/extra_links: {sorted(missing)}")
    return {t: kept[t] for t in full}  # same order as the config


def orphan_report(cfg: dict, tables: dict[str, pd.DataFrame]) -> list[str]:
    """FK check on the sample: a child value with no parent row. Should match the full data (Olist has a few by nature)."""
    out = []
    for r in cfg.get("relationships", []):
        c, cc = _split(r["from"])
        p, pc = _split(r["to"])
        vals = tables[c][cc]
        vals = vals[vals != ""]
        n = int((~vals.isin(tables[p][pc])).sum())
        out.append(f"  {r['from']:<42} -> {r['to']:<45} orphans: {n}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="olist")
    ap.add_argument("--frac", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", help="output folder (default tests/fixtures/<dataset>_sample)")
    a = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "configs" / "datasets" / f"{a.dataset}.yaml").read_text(encoding="utf-8"))
    out = Path(a.out) if a.out else ROOT / "tests" / "fixtures" / f"{a.dataset}_sample"
    out.mkdir(parents=True, exist_ok=True)

    tables = build_sample(cfg, a.frac, a.seed)
    print(f"sample of {a.dataset} (frac={a.frac}, seed={a.seed}) -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    for t, df in tables.items():
        df.to_csv(out / cfg["source"]["tables"][t], index=False)
        print(f"  {t:<22} {len(df):>7} rows")
    for col in cfg["sample"].get("cover", []):
        print(f"  coverage of {col}: " + ", ".join(f"{k}={v}" for k, v in tables[cfg['sample']['root']['table']][col].value_counts().items()))
    print("FK check on the sample:")
    print("\n".join(orphan_report(cfg, tables)))


if __name__ == "__main__":
    main()
