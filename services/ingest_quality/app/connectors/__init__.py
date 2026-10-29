from __future__ import annotations

from pathlib import Path
from typing import Any

from .api_connector import APIConnector
from .base import BaseConnector
from .csv_connector import CSVConnector
from .sql_connector import SQLConnector


def get_connector(config: dict[str, Any], root_dir: Path | None = None) -> BaseConnector:
    """Factory to get the appropriate connector based on config['type']."""
    source_type = config.get("type", "").lower()
    if source_type == "csv":
        return CSVConnector(config, root_dir=root_dir)
    elif source_type in ("sql", "sqlite", "duckdb", "postgres", "postgresql"):
        return SQLConnector(config, root_dir=root_dir)
    elif source_type in ("api", "rest", "http"):
        return APIConnector(config, root_dir=root_dir)
    else:
        raise ValueError(f"Unsupported connector type: '{source_type}'. Supported: csv, sql, api")


__all__ = ["BaseConnector", "CSVConnector", "SQLConnector", "APIConnector", "get_connector"]

