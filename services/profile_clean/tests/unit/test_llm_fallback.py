from __future__ import annotations

import pandas as pd
from app.cleaner_llm import run_llm_advisory
from app.cleaner_rules import CleanState
from app.lineage import LineageTracker


def test_malformed_llm_fallback(monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "0")

    def bad_chat(*_a, **_k):
        raise RuntimeError("invalid json twice")

    monkeypatch.setattr("app.cleaner_llm.chat_json", bad_chat)
    state = CleanState()
    tables = {"products": pd.DataFrame({"product_id": ["p1"], "product_weight_g": [None]})}
    rules = {"llm_advisory": {"enabled": True, "allowed_actions": ["impute_median"]}}
    lineage = LineageTracker("r1")
    calls = run_llm_advisory(tables, rules, None, lineage, state, set(), [0])
    assert calls == []
    assert any("LLM" in w for w in state.warnings)
