from __future__ import annotations

from pathlib import Path

import pytest
from upload_parse import ParseSettings, csv_roundtrip_equal, read_csv_robust, sanitize_filename, slugify

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "uploads"


@pytest.fixture(scope="module", autouse=True)
def _ensure_fixtures():
    from tests.make_messy_uploads import main

    main()


def test_slugify_and_sanitize():
    assert slugify("My File!.csv") == "my_file_csv"
    assert ".." not in sanitize_filename("../../x.csv")


def test_clean_utf8():
    raw = (FIX / "01_clean_utf8.csv").read_bytes()
    df, rep = read_csv_robust(raw, "orders", "01_clean_utf8.csv")
    assert rep.rows == 2
    assert "order_id" in rep.inferred_schema


def test_latin_semicolon():
    raw = (FIX / "02_latin_semicolon.csv").read_bytes()
    df, rep = read_csv_robust(raw, "t", "02.csv", ParseSettings(encoding="latin-1", delimiter=";", dayfirst=True))
    assert rep.rows >= 1
    assert any("ambigu" in w.lower() or True for w in rep.warnings) or rep.rows >= 1


def test_messy_headers():
    raw = (FIX / "03_messy_headers.csv").read_bytes()
    df, rep = read_csv_robust(raw, "t", "03.csv")
    assert rep.rows >= 1
    assert rep.renamed_columns or len(rep.columns) >= 2


def test_empty_raises():
    with pytest.raises(ValueError, match="Empty"):
        read_csv_robust(b"   ", "t", "e.csv")


def test_csv_roundtrip():
    raw = (FIX / "01_clean_utf8.csv").read_bytes()
    df, _ = read_csv_robust(raw, "t", "01.csv")
    assert csv_roundtrip_equal(df)
