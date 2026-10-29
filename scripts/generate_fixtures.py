"""Generates tiny, consistent ~100-row test fixtures for Olist in tests/fixtures/olist/.

Maintains referential integrity between tables so contract, unit, and smoke tests can run
blazingly fast without needing the full 1.5M rows dataset.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "olist"
OUT_DIR = ROOT / "tests" / "fixtures" / "olist"


def generate_fixtures(sample_orders: int = 100) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating ~{sample_orders} rows fixtures in {OUT_DIR}...")

    # 1. Orders
    orders_df = pd.read_csv(RAW_DIR / "olist_orders_dataset.csv")
    orders_sampled = orders_df.head(sample_orders).copy()
    orders_sampled.to_csv(OUT_DIR / "olist_orders_dataset.csv", index=False)
    order_ids = set(orders_sampled["order_id"])
    customer_ids = set(orders_sampled["customer_id"])

    # 2. Customers
    cust_df = pd.read_csv(RAW_DIR / "olist_customers_dataset.csv")
    cust_sampled = cust_df[cust_df["customer_id"].isin(customer_ids)].copy()
    cust_sampled.to_csv(OUT_DIR / "olist_customers_dataset.csv", index=False)

    # 3. Order Items
    items_df = pd.read_csv(RAW_DIR / "olist_order_items_dataset.csv")
    items_sampled = items_df[items_df["order_id"].isin(order_ids)].copy()
    items_sampled.to_csv(OUT_DIR / "olist_order_items_dataset.csv", index=False)
    product_ids = set(items_sampled["product_id"])
    seller_ids = set(items_sampled["seller_id"])

    # 4. Payments
    payments_df = pd.read_csv(RAW_DIR / "olist_order_payments_dataset.csv")
    pay_sampled = payments_df[payments_df["order_id"].isin(order_ids)].copy()
    pay_sampled.to_csv(OUT_DIR / "olist_order_payments_dataset.csv", index=False)

    # 5. Reviews
    rev_df = pd.read_csv(RAW_DIR / "olist_order_reviews_dataset.csv")
    rev_sampled = rev_df[rev_df["order_id"].isin(order_ids)].copy()
    rev_sampled.to_csv(OUT_DIR / "olist_order_reviews_dataset.csv", index=False)

    # 6. Products
    prod_df = pd.read_csv(RAW_DIR / "olist_products_dataset.csv")
    prod_sampled = prod_df[prod_df["product_id"].isin(product_ids)].copy()
    prod_sampled.to_csv(OUT_DIR / "olist_products_dataset.csv", index=False)

    # 7. Sellers
    sell_df = pd.read_csv(RAW_DIR / "olist_sellers_dataset.csv")
    sell_sampled = sell_df[sell_df["seller_id"].isin(seller_ids)].copy()
    sell_sampled.to_csv(OUT_DIR / "olist_sellers_dataset.csv", index=False)

    # 8. Geolocation
    geo_df = pd.read_csv(RAW_DIR / "olist_geolocation_dataset.csv")
    geo_sampled = geo_df.head(200).copy()
    geo_sampled.to_csv(OUT_DIR / "olist_geolocation_dataset.csv", index=False)

    # 9. Translation
    trans_df = pd.read_csv(RAW_DIR / "product_category_name_translation.csv")
    trans_df.to_csv(OUT_DIR / "product_category_name_translation.csv", index=False)

    print("Fixtures generated successfully!")


if __name__ == "__main__":
    generate_fixtures()

