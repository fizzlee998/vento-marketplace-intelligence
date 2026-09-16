"""
Data Cleaning — Vento Marketplace Intelligence Project
=========================================================
Reads the client's Excel exports (data/raw/client_excel_exports/) and the
synthetic marketing-spend file, applies the treatments decided in
reports/phase3_data_quality_findings.md, and writes clean, validated CSVs
to data/processed/.

Every treatment below traces back to a specific numbered finding in the
Phase 3 report — see the comment above each function.

Run:
    python src/cleaning/clean_pipeline.py
"""

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "data" / "raw" / "client_excel_exports"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

DATE_COLS = [
    "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
    "order_delivered_customer_date", "order_estimated_delivery_date",
]

# Finding #5 — two category names have no English match in the provided
# translation file; map them by hand rather than leaving them blank.
CATEGORY_PATCH = {
    "pc_gamer": "Gaming PC",
    "portateis_cozinha_e_preparadores_de_alimentos": "Kitchen Prep Appliances",
}


def load_raw():
    orders = pd.read_excel(EXPORTS / "01_order_system_export.xlsx", sheet_name="Orders")
    customers = pd.read_excel(EXPORTS / "01_order_system_export.xlsx", sheet_name="Customers")
    payments = pd.read_excel(EXPORTS / "02_payments_processor_export.xlsx", sheet_name="Payments")
    items = pd.read_excel(EXPORTS / "03_logistics_partner_export.xlsx", sheet_name="OrderItems")
    sellers = pd.read_excel(EXPORTS / "03_logistics_partner_export.xlsx", sheet_name="Sellers")
    reviews = pd.read_excel(EXPORTS / "04_customer_reviews_export.xlsx", sheet_name="Reviews")
    products = pd.read_excel(EXPORTS / "05_product_catalog_export.xlsx", sheet_name="Products")
    cat_tr = pd.read_excel(EXPORTS / "05_product_catalog_export.xlsx", sheet_name="CategoryTranslation")
    spend = pd.read_excel(EXPORTS / "06_marketing_spend_export_SYNTHETIC.xlsx", sheet_name="MarketingSpend_SYNTHETIC")
    geo = pd.read_csv(ROOT / "data" / "raw" / "olist_geolocation_dataset.csv")

    for col in DATE_COLS:
        orders[col] = pd.to_datetime(orders[col], errors="coerce")

    return dict(orders=orders, customers=customers, payments=payments, items=items,
                sellers=sellers, reviews=reviews, products=products, cat_tr=cat_tr,
                spend=spend, geo=geo)


# Finding #1 — delivery timestamps: nothing to impute (a missing delivery
# date is a real unknown, not a value we can safely guess), but we add an
# explicit exception flag so downstream KPIs can exclude these rows instead
# of silently mis-averaging.
def clean_orders(orders: pd.DataFrame) -> pd.DataFrame:
    orders = orders.copy()
    orders["is_delivered_without_date"] = (
        (orders["order_status"] == "delivered") & orders["order_delivered_customer_date"].isna()
    )
    orders["is_late_delivery"] = (
        orders["order_delivered_customer_date"] > orders["order_estimated_delivery_date"]
    )
    return orders


# Finding #2 — always expose customer_unique_id as the "real" customer key
# alongside the per-order customer_id, so downstream code can't accidentally
# use the wrong one for a customer count.
def clean_customers(customers: pd.DataFrame) -> pd.DataFrame:
    customers = customers.copy()
    customers["is_repeat_customer_id"] = customers.duplicated(subset=["customer_unique_id"], keep=False)
    return customers


# Finding #3 — deduplicate review rows; keep the most recent per order.
def clean_reviews(reviews: pd.DataFrame) -> pd.DataFrame:
    reviews = reviews.copy()
    reviews["review_creation_date"] = pd.to_datetime(reviews["review_creation_date"], errors="coerce")
    reviews = reviews.sort_values("review_creation_date")
    before = len(reviews)
    reviews = reviews.drop_duplicates(subset=["review_id"], keep="last")
    reviews = reviews.sort_values("review_creation_date").drop_duplicates(subset=["order_id"], keep="last")
    reviews["has_comment_text"] = reviews["review_comment_message"].notna()
    after = len(reviews)
    print(f"  reviews: {before} -> {after} rows after de-duplication")
    return reviews


# Finding #4 + #5 — tag missing categories instead of dropping products;
# patch the two untranslated category names.
def clean_products(products: pd.DataFrame, cat_tr: pd.DataFrame) -> pd.DataFrame:
    products = products.copy()
    products["product_category_name"] = products["product_category_name"].fillna("uncategorized")

    cat_tr = cat_tr.copy()
    patch_rows = pd.DataFrame(
        [{"product_category_name": k, "product_category_name_english": v} for k, v in CATEGORY_PATCH.items()]
    )
    cat_tr = pd.concat([cat_tr, patch_rows], ignore_index=True)
    cat_tr.loc[len(cat_tr)] = ["uncategorized", "Uncategorized"]

    products = products.merge(cat_tr, on="product_category_name", how="left")
    products["product_category_name_english"] = products["product_category_name_english"].fillna("Uncategorized")
    return products


# Finding #7 — flag (don't silently pick a winner between) mismatched
# payment vs. order-item totals.
def build_payment_reconciliation(items: pd.DataFrame, payments: pd.DataFrame) -> pd.DataFrame:
    item_totals = items.groupby("order_id").apply(lambda d: (d["price"] + d["freight_value"]).sum())
    item_totals.name = "item_total"
    payment_totals = payments.groupby("order_id")["payment_value"].sum()
    payment_totals.name = "payment_total"
    recon = pd.concat([item_totals, payment_totals], axis=1).reset_index()
    recon["payment_reconciliation_flag"] = (recon["item_total"] - recon["payment_total"]).abs() > 0.5
    return recon


# Finding #8 — isolate zero-value / zero-installment payment rows rather
# than silently including them in averages.
def clean_payments(payments: pd.DataFrame) -> pd.DataFrame:
    payments = payments.copy()
    payments["is_zero_value_row"] = payments["payment_value"] == 0
    payments["is_zero_installments"] = payments["payment_installments"] == 0
    return payments


# Finding #9 — collapse the geolocation table to one row per zip-code
# prefix (mean lat/lng) BEFORE it is ever joined to anything else.
def clean_geolocation(geo: pd.DataFrame) -> pd.DataFrame:
    agg = (
        geo.groupby("geolocation_zip_code_prefix")
        .agg(
            geolocation_lat=("geolocation_lat", "mean"),
            geolocation_lng=("geolocation_lng", "mean"),
            geolocation_city=("geolocation_city", lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0]),
            geolocation_state=("geolocation_state", lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0]),
        )
        .reset_index()
    )
    return agg


def run():
    print("Loading raw client exports...")
    raw = load_raw()

    print("Cleaning orders...")
    orders = clean_orders(raw["orders"])

    print("Cleaning customers...")
    customers = clean_customers(raw["customers"])

    print("Cleaning reviews...")
    reviews = clean_reviews(raw["reviews"])

    print("Cleaning products + category translation...")
    products = clean_products(raw["products"], raw["cat_tr"])

    print("Building payment reconciliation table...")
    recon = build_payment_reconciliation(raw["items"], raw["payments"])

    print("Cleaning payments...")
    payments = clean_payments(raw["payments"])

    print("Aggregating geolocation to one row per zip prefix...")
    geo = clean_geolocation(raw["geo"])

    outputs = {
        "orders_clean.csv": orders,
        "customers_clean.csv": customers,
        "order_items_clean.csv": raw["items"],
        "sellers_clean.csv": raw["sellers"],
        "payments_clean.csv": payments,
        "payment_reconciliation.csv": recon,
        "reviews_clean.csv": reviews,
        "products_clean.csv": products,
        "geolocation_clean.csv": geo,
        "marketing_spend_synthetic.csv": raw["spend"],
    }

    for filename, df in outputs.items():
        path = PROCESSED / filename
        df.to_csv(path, index=False)
        print(f"  wrote {filename}: {df.shape}")

    print("\nDone. Clean tables are in data/processed/.")


if __name__ == "__main__":
    run()
