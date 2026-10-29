from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .base import BaseConnector


class CSVConnector(BaseConnector):
    """Connector for reading tables from CSV files."""

    def load(self) -> dict[str, pd.DataFrame]:
        base_path_str = self.config.get("path", "")
        base_path = Path(base_path_str)
        if not base_path.is_absolute():
            base_path = (self.root_dir / base_path).resolve()

        tables_cfg = self.config.get("tables", {})
        dataframes: dict[str, pd.DataFrame] = {}

        for table_name, filename in tables_cfg.items():
            file_path = base_path / filename
            if not file_path.exists():
                # Also check relative to root directly if not found
                alt_path = (self.root_dir / filename).resolve()
                if alt_path.exists():
                    file_path = alt_path
                else:
                    raise FileNotFoundError(f"CSV file not found for table '{table_name}': {file_path}")

            df = pd.read_csv(file_path, low_memory=False)
            dataframes[table_name] = df

        return dataframes

