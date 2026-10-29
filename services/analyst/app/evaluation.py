"""BO6 eval (POST /v1/eval), all synthetic so the truth is known:
1. anomaly recall/precision: 20 seasonal + trending series, one planted spike each (spec target recall >= 90%);
2. driver decomposition sums to the total delta (additive and ratio), tolerance 1e-6, on 200 random cases."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import analysis as A


def run_eval(seed: int = 7) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    tp = fp = fn = 0
    for _ in range(20):
        n = 24
        x = np.arange(n)
        base = 100 + 2 * x + 5 * np.sin(2 * np.pi * x / 12) + rng.normal(0, 2, n)
        k = int(rng.integers(4, n - 2))
        base[k] += rng.choice([-1, 1]) * rng.uniform(25, 40)
        s = pd.Series(base, index=[f"p{i:02d}" for i in range(n)])
        found = {a["period"] for a in A.anomalies(s)}
        tp += f"p{k:02d}" in found
        fn += f"p{k:02d}" not in found
        fp += len(found - {f"p{k:02d}"})
    sums_ok = 0
    for _ in range(200):
        segs = [f"s{i}" for i in range(int(rng.integers(2, 8)))]
        rows = []
        for p in ("a", "b"):
            for sgm in segs:
                rows.append({"period": p, "dimension_value": sgm, "value": float(rng.uniform(1, 100)), "n": int(rng.integers(1, 50))})
        cut = pd.DataFrame(rows)
        additive = bool(rng.integers(0, 2))
        tot = {p: (cut[cut.period == p].value.sum() if additive else
                   (cut[cut.period == p].value * cut[cut.period == p].n).sum() / cut[cut.period == p].n.sum()) for p in ("a", "b")}
        dec = A.decompose(cut, "b", "a", additive, float(tot["b"]), float(tot["a"]))
        sums_ok += abs(sum(c["delta"] for c in dec["contributions"]) - dec["total_delta"]) < 1e-6
    return {"anomaly_recall": round(tp / (tp + fn), 3), "anomaly_precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "planted_series": 20, "driver_sum_to_delta_rate": round(sums_ok / 200, 3)}
