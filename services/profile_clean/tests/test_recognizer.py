from __future__ import annotations

import pandas as pd
from app.recognizer import recognize_table


def test_email_semantic_type():
    df = pd.DataFrame({"contact_email": ["a@b.com", "bad", "c@d.org"]})
    rec = recognize_table("t", df)[0]
    assert rec.semantic_type == "email"
    assert rec.confidence >= 0.85


def test_currency_proposed_action():
    df = pd.DataFrame({"unit_price": ["$10.00", "$20.50", "€ 9,00"]})
    rec = recognize_table("t", df)[0]
    assert rec.semantic_type in ("currency", "unknown", "categorical")
    assert rec.role in ("categorical", "continuous_numeric", "id")
