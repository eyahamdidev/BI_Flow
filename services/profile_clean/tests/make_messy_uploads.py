"""Generate messy CSV fixtures under tests/fixtures/uploads/."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "fixtures" / "uploads"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # 1 clean utf-8
    pd.DataFrame({"order_id": ["a1", "a2"], "amount": [10.5, 20.0], "note": ["x", "y"]}).to_csv(
        OUT / "01_clean_utf8.csv", index=False
    )
    # 2 latin-1 semicolon
    text = "id;montant;date\n1;12,5;15/03/2024\n2;8,0;N/A\n"
    (OUT / "02_latin_semicolon.csv").write_bytes(text.encode("latin-1"))
    # 3 BOM dup headers messy
    (OUT / "03_messy_headers.csv").write_text(
        "\ufeffid,id,name,\n1,1,foo,\n2,2,bar,\n,bad,line,\n",
        encoding="utf-8",
    )
    # 4 dirty business data
    pd.DataFrame(
        {
            "order_id": ["001", "001", "002", "003"],
            "zip": ["01310", "01310", "75001", "00002"],
            "price": [10.0, 10.0, -5.0, 100.0],
            "start_date": ["2024-01-01", "2024-01-01", "2024-02-01", "2024-03-01"],
            "end_date": ["2024-01-05", "2024-01-05", "2024-01-01", "2024-03-10"],
            "category": ["  A ", "  a ", "B", "B"],
            "sparse": [None, "x", None, None],
            "all_null": [None, None, None, None],
            "constant": [1, 1, 1, 1],
            "weight": [1.0, 1.0, 99999.0, 2.0],
        }
    ).to_csv(OUT / "04_dirty.csv", index=False)
    # 5 parent child
    pd.DataFrame({"customer_id": ["c1", "c2"], "name": ["Ann", "Bob"]}).to_csv(OUT / "05_customers.csv", index=False)
    pd.DataFrame({"order_id": ["o1", "o2"], "customer_id": ["c1", "c99"]}).to_csv(OUT / "05_orders.csv", index=False)
    # 7 empty / header only
    (OUT / "07_empty.csv").write_text("", encoding="utf-8")
    (OUT / "07_header_only.csv").write_text("a,b,c\n", encoding="utf-8")
    # 6 large (generate on demand marker file)
    (OUT / "06_large.placeholder").write_text("Run with --large to generate 500k rows", encoding="utf-8")
    if __import__("sys").argv[-1:] == ["--large"]:
        n = 500_000
        pd.DataFrame({"id": range(n), "value": [i % 1000 for i in range(n)]}).to_csv(OUT / "06_large.csv", index=False)
    print(f"Wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()
