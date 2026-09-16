"""
Transformation — Vento Marketplace Intelligence Project
===========================================================
Reads the clean tables in data/processed/ and builds the analytical marts
that the SQL database (Phase 6) and business analysis (Phase 8) are built
on top of:

  - fact_order_items.csv   one row per item sold (the most granular fact)
  - fact_orders.csv        one row per order, aggregated
  - dim_customers.csv      one row per real customer (customer_unique_id)
  - dim_sellers.csv        one row per seller, with performance/risk signals

Run:
    python src/transformation/build_marts.py
"""

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
MARTS = PROCESSED / "marts"
MARTS.mkdir(parents=True, exist_ok=True)


def load_clean():
    return dict(
        orders=pd.read_csv(PROCESSED / "orders_clean.csv", parse_dates=[
            "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
            "order_delivered_customer_date", "order_estimated_delivery_date"]),
        customers=pd.read_csv(PROCESSED / "customers_clean.csv"),
        items=pd.read_csv(PROCESSED / "order_items_clean.csv"),
        sellers=pd.read_csv(PROCESSED / "sellers_clean.csv"),
        payments=pd.read_csv(PROCESSED / "payments_clean.csv"),
        recon=pd.read_csv(PROCESSED / "payment_reconciliation.csv"),
        reviews=pd.read_csv(PROCESSED / "reviews_clean.csv"),
        products=pd.read_csv(PROCESSED / "products_clean.csv"),
    )


def build_fact_order_items(t: dict) -> pd.DataFrame:
    """One row per item sold — the most granular fact table."""
    df = t["items"].merge(
        t["orders"][["order_id", "customer_id", "order_status", "order_purchase_timestamp",
                     "is_late_delivery", "is_delivered_without_date"]],
        on="order_id", how="left",
    )
    df = df.merge(t["customers"][["customer_id", "customer_unique_id", "customer_state", "customer_city"]],
                   on="customer_id", how="left")
    df = df.merge(t["sellers"][["seller_id", "seller_state", "seller_city"]], on="seller_id", how="left")
    df = df.merge(
        t["products"][["product_id", "product_category_name_english"]],
        on="product_id", how="left",
    )
    df["is_cross_state_shipment"] = df["customer_state"] != df["seller_state"]
    df["item_total_value"] = df["price"] + df["freight_value"]
    return df


def build_fact_orders(t: dict, fact_items: pd.DataFrame) -> pd.DataFrame:
    """One row per order, aggregated from items + payments + reviews."""
    item_agg = fact_items.groupby("order_id").agg(
        n_items=("order_item_id", "count"),
        n_distinct_sellers=("seller_id", "nunique"),
        item_price_total=("price", "sum"),
        freight_total=("freight_value", "sum"),
        has_cross_state_shipment=("is_cross_state_shipment", "any"),
    ).reset_index()

    payment_agg = t["payments"].groupby("order_id").agg(
        payment_total=("payment_value", "sum"),
        n_payment_methods=("payment_type", "nunique"),
        max_installments=("payment_installments", "max"),
        primary_payment_type=("payment_type", lambda s: s.mode().iat[0] if not s.mode().empty else None),
    ).reset_index()

    review_agg = t["reviews"].groupby("order_id").agg(
        review_score=("review_score", "first"),
        has_comment_text=("has_comment_text", "first"),
    ).reset_index()

    fact_orders = t["orders"].merge(
        t["customers"][["customer_id", "customer_unique_id", "customer_state", "customer_city"]],
        on="customer_id", how="left",
    )
    fact_orders = fact_orders.merge(item_agg, on="order_id", how="left")
    fact_orders = fact_orders.merge(payment_agg, on="order_id", how="left")
    fact_orders = fact_orders.merge(review_agg, on="order_id", how="left")
    fact_orders = fact_orders.merge(
        t["recon"][["order_id", "payment_reconciliation_flag"]], on="order_id", how="left"
    )

    fact_orders["order_total_value"] = fact_orders["item_price_total"] + fact_orders["freight_total"]
    fact_orders["days_to_deliver"] = (
        fact_orders["order_delivered_customer_date"] - fact_orders["order_purchase_timestamp"]
    ).dt.days

    return fact_orders


def build_dim_customers(fact_orders: pd.DataFrame) -> pd.DataFrame:
    """One row per real customer (customer_unique_id), with RFM-style signals."""
    delivered = fact_orders[fact_orders["order_status"] == "delivered"]
    snapshot_date = fact_orders["order_purchase_timestamp"].max()

    agg = delivered.groupby("customer_unique_id").agg(
        n_orders=("order_id", "nunique"),
        total_spent=("order_total_value", "sum"),
        avg_order_value=("order_total_value", "mean"),
        first_order_date=("order_purchase_timestamp", "min"),
        last_order_date=("order_purchase_timestamp", "max"),
        avg_review_score=("review_score", "mean"),
        primary_state=("customer_state", lambda s: s.mode().iat[0] if not s.mode().empty else None),
    ).reset_index()

    agg["is_repeat_customer"] = agg["n_orders"] > 1
    agg["days_since_last_order"] = (snapshot_date - agg["last_order_date"]).dt.days
    agg["customer_lifespan_days"] = (agg["last_order_date"] - agg["first_order_date"]).dt.days

    return agg


def build_dim_sellers(fact_items: pd.DataFrame, fact_orders: pd.DataFrame) -> pd.DataFrame:
    """One row per seller, with the performance/risk signals Phase 8 will rank on."""
    order_status = fact_orders[["order_id", "is_late_delivery", "is_delivered_without_date",
                                 "review_score", "order_status"]]
    items_with_status = fact_items.merge(order_status, on="order_id", how="left", suffixes=("", "_order"))

    agg = items_with_status.groupby("seller_id").agg(
        n_orders=("order_id", "nunique"),
        n_items_sold=("order_item_id", "count"),
        total_revenue=("item_total_value", "sum"),
        avg_review_score=("review_score", "mean"),
        late_delivery_count=("is_late_delivery", "sum"),
        seller_state=("seller_state", "first"),
        seller_city=("seller_city", "first"),
    ).reset_index()

    agg["late_delivery_rate"] = agg["late_delivery_count"] / agg["n_orders"]
    return agg


def run():
    print("Loading clean tables...")
    t = load_clean()

    print("Building fact_order_items...")
    fact_items = build_fact_order_items(t)

    print("Building fact_orders...")
    fact_orders = build_fact_orders(t, fact_items)

    print("Building dim_customers...")
    dim_customers = build_dim_customers(fact_orders)

    print("Building dim_sellers...")
    dim_sellers = build_dim_sellers(fact_items, fact_orders)

    outputs = {
        "fact_order_items.csv": fact_items,
        "fact_orders.csv": fact_orders,
        "dim_customers.csv": dim_customers,
        "dim_sellers.csv": dim_sellers,
    }
    for filename, df in outputs.items():
        path = MARTS / filename
        df.to_csv(path, index=False)
        print(f"  wrote {filename}: {df.shape}")

    print("\nDone. Marts are in data/processed/marts/.")


if __name__ == "__main__":
    run()
