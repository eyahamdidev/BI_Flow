"""Tiny FastAPI mock API server for demoing APIConnector with paginated data."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query

mock_api_app = FastAPI(title="BIFlow Mock API Server")

# In-memory sample records for API demo
_ORDERS_DB = [
    {"order_id": f"ord_{i:04d}", "customer_id": f"cust_{i % 10:04d}", "order_status": "delivered", "price": round(10.5 * (i + 1), 2)}
    for i in range(1, 26)  # 25 orders
]

_CUSTOMERS_DB = [
    {"customer_id": f"cust_{i:04d}", "customer_unique_id": f"uniq_{i:04d}", "customer_state": "SP"}
    for i in range(10)
]


@mock_api_app.get("/orders")
def get_orders(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1)) -> dict[str, Any]:
    start = (page - 1) * page_size
    end = start + page_size
    items = _ORDERS_DB[start:end]
    has_next = end < len(_ORDERS_DB)
    return {"items": items, "page": page, "page_size": page_size, "total": len(_ORDERS_DB), "has_next": has_next}


@mock_api_app.get("/customers")
def get_customers(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1)) -> dict[str, Any]:
    start = (page - 1) * page_size
    end = start + page_size
    items = _CUSTOMERS_DB[start:end]
    has_next = end < len(_CUSTOMERS_DB)
    return {"items": items, "page": page, "page_size": page_size, "total": len(_CUSTOMERS_DB), "has_next": has_next}

