from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from .base import BaseConnector


class APIConnector(BaseConnector):
    """Connector for reading tables from REST APIs with pagination support."""

    def __init__(self, config: dict[str, Any], root_dir: Any = None) -> None:
        super().__init__(config, root_dir)
        self.base_url = self.config.get("base_url", "").rstrip("/")
        self.headers = self.config.get("headers", {})
        self.timeout = self.config.get("timeout_s", 30)

    def _fetch_records(self, endpoint_cfg: str | dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(endpoint_cfg, str):
            endpoint = endpoint_cfg
            page_param = "page"
            page_size_param = "page_size"
            page_size = 100
            max_pages = 100
            data_key = None
        else:
            endpoint = endpoint_cfg.get("endpoint", "")
            page_param = endpoint_cfg.get("page_param", "page")
            page_size_param = endpoint_cfg.get("page_size_param", "page_size")
            page_size = endpoint_cfg.get("page_size", 100)
            max_pages = endpoint_cfg.get("max_pages", 100)
            data_key = endpoint_cfg.get("data_key")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        all_records: list[dict[str, Any]] = []

        with httpx.Client(timeout=self.timeout) as client:
            page = 1
            while page <= max_pages:
                params = {page_param: page, page_size_param: page_size}
                resp = client.get(url, params=params, headers=self.headers)
                resp.raise_for_status()
                payload = resp.json()

                if isinstance(payload, list):
                    records = payload
                elif isinstance(payload, dict):
                    if data_key and data_key in payload:
                        records = payload[data_key]
                    elif "items" in payload:
                        records = payload["items"]
                    elif "data" in payload:
                        records = payload["data"]
                    elif "results" in payload:
                        records = payload["results"]
                    else:
                        # Single record or dict values
                        records = [payload]
                else:
                    break

                if not records:
                    break

                all_records.extend(records)

                # Stop if pagination indicates completion
                if isinstance(payload, dict):
                    if payload.get("has_next") is False:
                        break
                    total = payload.get("total")
                    if total is not None and len(all_records) >= total:
                        break

                if len(records) < page_size:
                    break

                page += 1

        return all_records

    def load(self) -> dict[str, pd.DataFrame]:
        tables_cfg = self.config.get("tables", {})
        dataframes: dict[str, pd.DataFrame] = {}

        for table_name, endpoint_cfg in tables_cfg.items():
            records = self._fetch_records(endpoint_cfg)
            df = pd.DataFrame(records) if records else pd.DataFrame()
            dataframes[table_name] = df

        return dataframes

