"""Unit tests for KPI SQL handling and the built-in embedding (no warehouse, no network)."""
import duckdb
import numpy as np
from app.compute import aggregation_kind, cut_sql, total_sql
from app.retrieval import hashing_embed

REV = "SELECT date_trunc('month', ts) AS period, SUM(amount) AS value FROM fact_orders WHERE status='delivered' GROUP BY 1"
AOV = "SELECT date_trunc('month', ts) AS period, SUM(amount)/COUNT(*) AS value FROM fact_orders WHERE status='delivered' GROUP BY 1"


def test_aggregation_kind():
    assert aggregation_kind(REV) == "additive"
    assert aggregation_kind(AOV) == "ratio"
    assert aggregation_kind("SELECT period, AVG(x) AS value FROM t GROUP BY 1") == "ratio"
    assert aggregation_kind("WITH f AS (SELECT 1) SELECT 1") == "ratio"  # not the KPI shape: never assumed additive


def test_dimension_cut_matches_total():
    con = duckdb.connect()
    con.execute("CREATE TABLE fact_orders AS SELECT * FROM (VALUES "
                "(TIMESTAMP '2018-01-03', 10.0, 'delivered', 'SP'), (TIMESTAMP '2018-01-09', 5.0, 'delivered', 'RJ'), "
                "(TIMESTAMP '2018-01-10', 7.0, 'canceled', 'RJ'), (TIMESTAMP '2018-02-01', 4.0, 'delivered', NULL)) "
                "t(ts, amount, status, state)")
    tot = con.execute(total_sql(REV)).fetchall()
    cut = con.execute(cut_sql(REV, "state")).fetchall()
    by_period = {}
    for period, _dv, value, _n in cut:
        by_period[period] = by_period.get(period, 0) + value
    assert {p: v for p, v, _n in tot} == by_period          # additive: segments add up to the total
    assert any(dv == "unknown" for _p, dv, _v, _n in cut)   # NULL dimension kept as 'unknown', never dropped


def test_hashing_embedding_is_deterministic_and_typo_tolerant():
    a, b, c = hashing_embed(["revenue by state", "revnue by state", "late delivery rate"])
    assert a == hashing_embed(["revenue by state"])[0]
    assert np.dot(a, b) > np.dot(a, c)
