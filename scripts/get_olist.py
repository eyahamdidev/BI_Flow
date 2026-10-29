"""Download the full Olist dataset (Kaggle olistbr/brazilian-ecommerce, ~45 MB zip) into data/raw/olist/.

Runs inside a container (no Python needed on your machine); the start scripts call it with `-Full` / `--full`:
    docker compose run --rm --no-deps -v ./scripts:/srv/scripts:ro gateway python /srv/scripts/get_olist.py
Standard library only. If Kaggle is blocked on your network, download the zip from
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce and unzip the 9 CSVs into data/raw/olist/.
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce"
EXPECTED = 9


def main() -> None:
    out = Path(os.getenv("DATA_DIR", "data")) / "raw" / "olist"
    if len(list(out.glob("*.csv"))) >= EXPECTED:
        print(f"Olist already present in {out}")
        return
    out.mkdir(parents=True, exist_ok=True)
    print(f"downloading {URL} ...", flush=True)
    try:
        with urllib.request.urlopen(URL, timeout=300) as r:  # noqa: S310 (fixed https URL)
            blob = r.read()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"download failed ({e}). Download it by hand from Kaggle and unzip the 9 CSVs into {out}.")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv") and "/" not in n.strip("/")]
        for n in names:
            (out / n).write_bytes(z.read(n))
    print(f"{len(names)} CSV files written to {out}")


if __name__ == "__main__":
    main()
