"""Outlier detection benchmark on injected spikes."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.neighbors import LocalOutlierFactor

SEED = 42


def _labels_from_manifest(n: int, spike_rows: list[int]) -> np.ndarray:
    y = np.zeros(n, dtype=int)
    for i in spike_rows:
        if 0 <= i < n:
            y[i] = 1
    return y


def bench_series(values: np.ndarray, y_true: np.ndarray) -> dict:
    s = pd.Series(values)
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    pred_iqr = ((s < lo) | (s > hi)).astype(int).values
    med = s.median()
    mad = (s - med).abs().median()
    pred_mad = np.zeros(len(s), dtype=int)
    if mad > 0:
        pred_mad = ((s - med).abs() / mad > 3.5).astype(int)
    X = s.values.reshape(-1, 1)
    pred_if = (IsolationForest(random_state=SEED, contamination=0.01).fit_predict(X) == -1).astype(int)
    pred_lof = (LocalOutlierFactor(n_neighbors=min(20, len(s) - 1), contamination=0.01).fit_predict(X) == -1).astype(
        int
    )

    def scores(name: str, pred: np.ndarray) -> dict:
        if y_true.sum() == 0:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
        return {
            "precision": float(precision_score(y_true, pred, zero_division=0)),
            "recall": float(recall_score(y_true, pred, zero_division=0)),
            "f1": float(f1_score(y_true, pred, zero_division=0)),
        }

    return {"iqr": scores("iqr", pred_iqr), "mad": scores("mad", pred_mad), "iforest": scores("if", pred_if), "lof": scores("lof", pred_lof)}


def run(corrupted_dir: Path) -> dict:
    gt_path = corrupted_dir / "ground_truth.json"
    items_path = corrupted_dir / "order_items.parquet"
    if not gt_path.exists() or not items_path.exists():
        return {"skipped": True}
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    df = pd.read_parquet(items_path)
    spikes = [x["row"] for x in gt.get("spikes", []) if x.get("table") == "order_items"]
    y = _labels_from_manifest(len(df), spikes)
    return bench_series(df["freight_value"].fillna(0).values, y)


if __name__ == "__main__":
    import sys

    print(json.dumps(run(Path(sys.argv[1])), indent=2))
