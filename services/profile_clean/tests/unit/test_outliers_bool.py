"""Regression: IQR outlier detection must not crash on boolean columns."""
from __future__ import annotations

import pandas as pd
from app.cleaner_ml import apply_outliers
from app.column_roles import ColumnRoleInfo
from app.lineage import LineageTracker


class _State:
    quality_log: list
    review_queue: list
    warnings: list


def test_outliers_skip_bool_column():
    tables = {"main": pd.DataFrame({"flag": [True, True, False, True], "amount": [1.0, 2.0, 100.0, 3.0]})}
    state = _State()
    state.quality_log = []
    state.review_queue = []
    state.warnings = []
    rules = {
        "outliers": {
            "method": "iqr",
            "columns": ["main.flag", "main.amount"],
            "action": "flag",
        }
    }
    roles = {
        "main.flag": ColumnRoleInfo("binary_flag", "test", "bool"),
        "main.amount": ColumnRoleInfo("continuous_numeric", "test", "float"),
    }
    apply_outliers(tables, rules, LineageTracker("r"), state, roles)
    assert "amount__outlier" in tables["main"].columns
    assert "flag__outlier" not in tables["main"].columns
