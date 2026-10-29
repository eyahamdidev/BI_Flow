"""Unit tests for the staging generator (no dbt, no data: milliseconds)."""
import yaml
from app.staging import render_model, render_yaml

CFG = {
    "expected_schema": {"orders": {"order_id": "str", "amount": "float", "created": {"type": "datetime", "nullable": True}}},
    "etl": {"keys": {"orders": ["order_id"], "items": ["order_id", "line"]}, "cast": {"orders.shipped": "datetime"}},
    "relationships": [{"from": "items.order_id", "to": "orders.order_id"}],
}


def test_declared_columns_are_cast_and_others_pass_through():
    sql = render_model(CFG, "orders", ["order_id", "amount", "created", "shipped", "note"], "x.yaml")
    assert 'cast("order_id" as VARCHAR) as "order_id"' in sql
    assert 'cast("amount" as DOUBLE)' in sql
    assert 'cast("created" as TIMESTAMP)' in sql          # dict form {type: ...}
    assert 'cast("shipped" as TIMESTAMP)' in sql          # from etl.cast
    assert '"note" as "note"' in sql and 'cast("note"' not in sql
    assert "{{ source('raw', 'orders') }}" in sql          # dbt Jinja left intact for dbt
    import re

    assert len(re.findall(r'as "[^"]+",', sql)) == 4      # 5 columns -> 4 separators, no trailing comma


def test_strict_cast_never_try_cast():
    assert "try_cast" not in render_model(CFG, "orders", ["amount"], "x.yaml").lower()


def test_unknown_type_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="unknown type"):
        render_model({"expected_schema": {"t": {"c": "money"}}}, "t", ["c"], "x.yaml")


def test_tests_yaml_has_warn_keys_and_relationships():
    sources, staging = render_yaml(CFG, ["orders", "items"])
    assert yaml.safe_load(sources)["sources"][0]["schema"] == "raw"
    models = {m["name"]: m for m in yaml.safe_load(staging)["models"]}
    composite = models["stg_items"]["tests"][0]["unique"]
    assert "|| '-' ||" in composite["column_name"] and composite["config"]["severity"] == "warn"
    rel = [t for c in models["stg_items"]["columns"] if c["name"] == "order_id" for t in c["tests"] if "relationships" in t]
    assert rel[0]["relationships"]["to"] == "ref('stg_orders')"
    assert rel[0]["relationships"]["config"]["severity"] == "warn"
