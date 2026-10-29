from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd


class BaseConnector(ABC):
    """Abstract base connector for data ingestion."""

    def __init__(self, config: dict[str, Any], root_dir: Path | None = None) -> None:
        self.config = config
        self.root_dir = root_dir or Path.cwd()

    @abstractmethod
    def load(self) -> dict[str, pd.DataFrame]:
        """Load all configured tables into a dict of DataFrames keyed by table name."""
        raise NotImplementedError

