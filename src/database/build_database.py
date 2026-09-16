"""
Build Database — Vento Marketplace Intelligence Project
===========================================================
Creates sql/vento_marketplace.db from sql/schema.sql, loads every table
from data/processed/ + data/processed/marts/, and runs a handful of
smoke-test queries to confirm the load is correct before Phase 7 starts
writing real analysis on top of it.

Run:
    python src/database/build_database.py
"""

import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
MARTS = PROCESSED / "marts"
SQL_DIR = ROOT / "sql"
DB_PATH = SQL_DIR / "vento_marketplace.db"

TABLE_SOURCES = {
    "orders": MARTS / "fact_orders.csv",
    "order_items": MARTS / "fact_order_items.csv",
    "customers": MARTS / "dim_customers.csv",
    "sellers": MARTS / "dim_sellers.csv",
    "products": PROCESSED / "products_clean.csv",
    "geolocation": PROCESSED / "geolocation_clean.csv",
    "payments": PROCESSED / "payments_clean.csv",
    "reviews": PROCESSED / "reviews_clean.csv",
    "marketing_spend_synthetic": PROCESSED / "marketing_spend_synthetic.csv",
}

BOOL_COLUMNS = {
    "is_late_delivery", "is_delivered_without_date", "has_cross_state_shipment",
    "payment_reconciliation_flag", "has_comment_text", "is_cross_state_shipment",
    "is_repeat_customer", "is_zero_value_row", "is_zero_installments",
}


def build():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    schema_sql = (SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    for table_name, csv_path in TABLE_SOURCES.items():
        df = pd.read_csv(csv_path)
        for col in df.columns:
            if col in BOOL_COLUMNS:
                df[col] = df[col].astype("boolean").astype("Int64")
        df.to_sql(table_name, conn, if_exists="append", index=False)
        print(f"  loaded {table_name}: {len(df)} rows")

    conn.commit()
    return conn


def verify(conn: sqlite3.Connection):
    print("\n--- Verification queries ---")

    checks = [
        ("Row counts", """
            SELECT 'orders' t, COUNT(*) n FROM orders
            UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
            UNION ALL SELECT 'customers', COUNT(*) FROM customers
            UNION ALL SELECT 'sellers', COUNT(*) FROM sellers
            UNION ALL SELECT 'products', COUNT(*) FROM products
            UNION ALL SELECT 'geolocation', COUNT(*) FROM geolocation
            UNION ALL SELECT 'payments', COUNT(*) FROM payments
            UNION ALL SELECT 'reviews', COUNT(*) FROM reviews
            UNION ALL SELECT 'marketing_spend_synthetic', COUNT(*) FROM marketing_spend_synthetic
        """),
        ("Orders join to customers cleanly (should be 0 unmatched)", """
            SELECT COUNT(*) FROM orders o
            LEFT JOIN customers c ON o.customer_unique_id = c.customer_unique_id
            WHERE o.order_status = 'delivered' AND c.customer_unique_id IS NULL
        """),
        ("Top 3 states by delivered revenue", """
            SELECT customer_state, ROUND(SUM(order_total_value),2) revenue
            FROM orders WHERE order_status = 'delivered'
            GROUP BY customer_state ORDER BY revenue DESC LIMIT 3
        """),
        ("Worst 3 sellers by late-delivery rate (>=10 orders)", """
            SELECT seller_id, n_orders, ROUND(late_delivery_rate,3) late_rate, ROUND(avg_review_score,2) avg_score
            FROM sellers WHERE n_orders >= 10 ORDER BY late_delivery_rate DESC LIMIT 3
        """),
    ]

    for label, query in checks:
        print(f"\n{label}:")
        result = pd.read_sql(query, conn)
        print(result.to_string(index=False))


if __name__ == "__main__":
    print("Building database...")
    conn = build()
    verify(conn)
    conn.close()
    print(f"\nDone. Database written to {DB_PATH}")
