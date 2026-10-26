"""Mask 10% numeric values; compare imputers."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import KNNImputer, SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error

SEED = 42


def bench(df: pd.DataFrame, col: str) -> dict:
    rng = np.random.default_rng(SEED)
    s = df[col].dropna()
    if len(s) < 20:
        return {}
    idx = rng.choice(s.index, size=max(1, len(s) // 10), replace=False)
    true = df.loc[idx, col].copy()
    work = df.copy()
    work.loc[idx, col] = np.nan
    numeric = work.select_dtypes(include=[np.number]).columns.tolist()
    results = {}
    for name, imp in [
        ("median", SimpleImputer(strategy="median")),
        ("knn", KNNImputer(n_neighbors=5)),
    ]:
        sub = work[numeric].copy()
        pred = imp.fit_transform(sub)[:, numeric.index(col)]
        pred_s = pd.Series(pred, index=work.index)
        y_pred = pred_s.loc[idx]
        y_true = true
        results[name] = {
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
        }
    try:
        from sklearn.experimental import enable_iterative_imputer  # noqa: F401
        from sklearn.impute import IterativeImputer

        imp = IterativeImputer(random_state=SEED)
        pred = imp.fit_transform(work[numeric])[:, numeric.index(col)]
        y_pred = pd.Series(pred, index=work.index).loc[idx]
        results["iterative"] = {
            "rmse": float(np.sqrt(mean_squared_error(true, y_pred))),
            "mae": float(mean_absolute_error(true, y_pred)),
        }
    except Exception as e:
        results["iterative"] = {"failed": str(e)}
    return results


def run(data_dir: Path) -> dict:
    p = data_dir / "products.parquet"
    if not p.exists():
        return {"skipped": True}
    df = pd.read_parquet(p)
    if "product_weight_g" not in df.columns:
        return {"skipped": True}
    return bench(df, "product_weight_g")


if __name__ == "__main__":
    import sys

    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/fixtures/olist_mini")
    print(json.dumps(run(d), indent=2))
