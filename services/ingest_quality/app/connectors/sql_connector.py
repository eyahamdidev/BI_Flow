from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, inspect

from .base import BaseConnector


class SQLConnector(BaseConnector):
    """Connector for reading tables from SQL databases via SQLAlchemy (SQLite, DuckDB, PostgreSQL, etc.)."""

    def load(self) -> dict[str, pd.DataFrame]:
        url = self.config.get("url")
        if not url:
            raise ValueError("SQLConnector requires a 'url' in source configuration")

        # Handle relative sqlite path like sqlite:///path/to/db
        sqlite_prefix = "sqlite:///"
        if url.startswith(sqlite_prefix) and not url.startswith("sqlite:////") and ":memory:" not in url:
            rel_path = url[len(sqlite_prefix):]
            db_file = Path(rel_path)
            if not db_file.is_absolute():
                abs_db_file = (self.root_dir / db_file).resolve()
                # Windows path compatibility with sqlite:///
                clean_path = abs_db_file.as_posix()
                url = f"sqlite:///{clean_path}"

        engine = create_engine(url)
        tables_cfg = self.config.get("tables")
        dataframes: dict[str, pd.DataFrame] = {}

        try:
            with engine.connect() as conn:
                if isinstance(tables_cfg, dict):
                    for table_name, query_or_table in tables_cfg.items():
                        # If it's a SELECT query
                        if re.match(r"^\s*select\s+", query_or_table, re.IGNORECASE):
                            df = pd.read_sql_query(query_or_table, conn)
                        else:
                            df = pd.read_sql_table(query_or_table, conn)
                        dataframes[table_name] = df
                elif isinstance(tables_cfg, list):
                    for table_name in tables_cfg:
                        df = pd.read_sql_table(table_name, conn)
                        dataframes[table_name] = df
                else:
                    # If no tables specified, read all tables discovered via inspector
                    inspector = inspect(engine)
                    for table_name in inspector.get_table_names():
                        df = pd.read_sql_table(table_name, conn)
                        dataframes[table_name] = df
        finally:
            engine.dispose()

        return dataframes
