from __future__ import annotations

from pathlib import Path

import pandas as pd
from draft_yaml import generate_draft_yaml, id_columns_from_yaml, validate_yaml_structure

FIX = Path(__file__).parents[1] / "fixtures" / "uploads"


def test_yaml_keys_and_id_protection():
    df = pd.read_csv(FIX / "04_dirty.csv")
    cfg = generate_draft_yaml("uploaded_test", {"orders": df}, None, llm_enabled=False)
    assert not validate_yaml_structure(cfg)
    assert "cleaning_rules" in cfg
    ids = id_columns_from_yaml(cfg)
    assert any("order_id" in x for x in ids)
    ns = cfg["cleaning_rules"]["null_strategy"]
    assert ns["orders.order_id"]["strategy"] == "flag_only"
