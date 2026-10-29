"""Unit tests for the analysis maths (no I/O, no LLM)."""
import numpy as np
import pandas as pd
from app import analysis as A
from app.evaluation import run_eval
from app.insights import unsupported


def _cut(rows):
    return pd.DataFrame(rows, columns=["period", "dimension_value", "value", "n"])


def test_additive_decomposition_sums_to_delta():
    cut = _cut([("a", "SP", 100, 10), ("a", "RJ", 50, 5), ("b", "SP", 130, 12), ("b", "MG", 20, 2)])
    dec = A.decompose(cut, "b", "a", True, 150.0, 150.0)
    assert abs(sum(c["delta"] for c in dec["contributions"]) - dec["total_delta"]) < 1e-9
    assert {c["dimension_value"] for c in dec["contributions"]} == {"SP", "RJ", "MG"}  # RJ vanished, MG appeared


def test_ratio_decomposition_mix_plus_rate_and_sums():
    cut = _cut([("a", "x", 10.0, 50), ("a", "y", 20.0, 50), ("b", "x", 10.0, 80), ("b", "y", 20.0, 20)])
    t_a = (10 * 50 + 20 * 50) / 100
    t_b = (10 * 80 + 20 * 20) / 100
    dec = A.decompose(cut, "b", "a", False, t_b, t_a)
    assert abs(sum(c["delta"] for c in dec["contributions"]) - (t_b - t_a)) < 1e-9
    for c in dec["contributions"]:
        assert abs(c["mix"] + c["rate"] - c["delta"]) < 1e-9
        assert abs(c["rate"]) < 1e-9  # segment values did not change: the whole move is MIX


def test_unexplained_row_keeps_the_sum_exact():
    cut = _cut([("a", "x", 10.0, 1), ("b", "x", 12.0, 1)])
    dec = A.decompose(cut, "b", "a", True, 100.0, 90.0)  # total moved 10, the segment explains 2
    assert any(c["dimension_value"] == "(unexplained)" for c in dec["contributions"])
    assert abs(sum(c["delta"] for c in dec["contributions"]) - 10.0) < 1e-9


def test_incomplete_months_are_excluded():
    total = pd.DataFrame({"period": ["2016-09", "2016-10", "2017-01", "2017-02", "2017-03", "2018-09"],
                          "n": [1, 300, 800, 900, 1000, 16], "value": [1.0] * 6})
    assert A.complete_periods(total) == ["2016-10", "2017-01", "2017-02", "2017-03"]


def test_steady_growth_is_not_an_anomaly_but_a_spike_is():
    s = pd.Series(100 + 5 * np.arange(20.0), index=[f"p{i:02d}" for i in range(20)])
    assert A.anomalies(s) == []
    s.iloc[12] += 60
    found = A.anomalies(s)
    assert [a["period"] for a in found] == ["p12"] and found[0]["direction"] == "high"


def test_fact_check_accepts_percent_form_and_rejects_new_numbers():
    facts = {"actual": 0.0834, "expected": 0.061, "period": "2018-03"}
    assert unsupported("The late rate reached 8.3% in 2018-03 against 6.1% expected.", facts, "ratio") == []
    assert unsupported("The late rate rose by 2.2 points.", facts, "ratio") == ["2.2"]


def test_eval_targets():
    m = run_eval()
    assert m["anomaly_recall"] >= 0.9
    assert m["driver_sum_to_delta_rate"] == 1.0
