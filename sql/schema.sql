-- Vento Marketplace Intelligence Project — Analytical Database Schema
-- SQLite. Loaded from data/processed/ and data/processed/marts/ by
-- src/database/build_database.py

DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
    order_id                TEXT PRIMARY KEY,
    customer_id             TEXT,
    customer_unique_id      TEXT,
    customer_state          TEXT,
    customer_city           TEXT,
    order_status             TEXT,
    order_purchase_timestamp TEXT,
    order_approved_at        TEXT,
    order_delivered_carrier_date  TEXT,
    order_delivered_customer_date TEXT,
    order_estimated_delivery_date TEXT,
    is_late_delivery          INTEGER,
    is_delivered_without_date INTEGER,
    n_items                   INTEGER,
    n_distinct_sellers        INTEGER,
    item_price_total          REAL,
    freight_total              REAL,
    order_total_value          REAL,
    has_cross_state_shipment   INTEGER,
    payment_total               REAL,
    n_payment_methods           INTEGER,
    max_installments             INTEGER,
    primary_payment_type         TEXT,
    payment_reconciliation_flag  INTEGER,
    review_score                  REAL,
    has_comment_text               INTEGER,
    days_to_deliver                 REAL
);

DROP TABLE IF EXISTS order_items;
CREATE TABLE order_items (
    order_id              TEXT,
    order_item_id          INTEGER,
    product_id              TEXT,
    seller_id                TEXT,
    shipping_limit_date        TEXT,
    price                        REAL,
    freight_value                 REAL,
    customer_id                    TEXT,
    order_status                    TEXT,
    order_purchase_timestamp         TEXT,
    is_late_delivery                  INTEGER,
    is_delivered_without_date          INTEGER,
    customer_unique_id                  TEXT,
    customer_state                       TEXT,
    customer_city                         TEXT,
    seller_state                           TEXT,
    seller_city                             TEXT,
    product_category_name_english            TEXT,
    is_cross_state_shipment                   INTEGER,
    item_total_value                           REAL,
    PRIMARY KEY (order_id, order_item_id)
);

DROP TABLE IF EXISTS customers;
CREATE TABLE customers (
    customer_unique_id      TEXT PRIMARY KEY,
    n_orders                 INTEGER,
    total_spent                REAL,
    avg_order_value              REAL,
    first_order_date               TEXT,
    last_order_date                 TEXT,
    avg_review_score                  REAL,
    primary_state                      TEXT,
    is_repeat_customer                  INTEGER,
    days_since_last_order                 INTEGER,
    customer_lifespan_days                  INTEGER
);

DROP TABLE IF EXISTS sellers;
CREATE TABLE sellers (
    seller_id             TEXT PRIMARY KEY,
    n_orders                INTEGER,
    n_items_sold              INTEGER,
    total_revenue                REAL,
    avg_review_score               REAL,
    late_delivery_count               INTEGER,
    seller_state                        TEXT,
    seller_city                          TEXT,
    late_delivery_rate                     REAL
);

DROP TABLE IF EXISTS products;
CREATE TABLE products (
    product_id                     TEXT PRIMARY KEY,
    product_category_name           TEXT,
    product_name_lenght               REAL,
    product_description_lenght          REAL,
    product_photos_qty                    REAL,
    product_weight_g                        REAL,
    product_length_cm                        REAL,
    product_height_cm                          REAL,
    product_width_cm                             REAL,
    product_category_name_english                 TEXT
);

DROP TABLE IF EXISTS geolocation;
CREATE TABLE geolocation (
    geolocation_zip_code_prefix INTEGER PRIMARY KEY,
    geolocation_lat                REAL,
    geolocation_lng                  REAL,
    geolocation_city                   TEXT,
    geolocation_state                    TEXT
);

DROP TABLE IF EXISTS payments;
CREATE TABLE payments (
    order_id                TEXT,
    payment_sequential        INTEGER,
    payment_type                TEXT,
    payment_installments           INTEGER,
    payment_value                    REAL,
    is_zero_value_row                  INTEGER,
    is_zero_installments                 INTEGER
);

DROP TABLE IF EXISTS reviews;
CREATE TABLE reviews (
    review_id                TEXT PRIMARY KEY,
    order_id                   TEXT,
    review_score                 INTEGER,
    review_comment_title            TEXT,
    review_comment_message            TEXT,
    review_creation_date                TEXT,
    review_answer_timestamp               TEXT,
    has_comment_text                        INTEGER
);

DROP TABLE IF EXISTS marketing_spend_synthetic;
CREATE TABLE marketing_spend_synthetic (
    month           TEXT,
    channel           TEXT,
    spend_brl           REAL
);

-- Indexes on the columns everything else joins to
CREATE INDEX idx_orders_customer_unique_id ON orders(customer_unique_id);
CREATE INDEX idx_orders_status ON orders(order_status);
CREATE INDEX idx_orders_purchase_ts ON orders(order_purchase_timestamp);
CREATE INDEX idx_items_order_id ON order_items(order_id);
CREATE INDEX idx_items_seller_id ON order_items(seller_id);
CREATE INDEX idx_items_product_id ON order_items(product_id);
CREATE INDEX idx_payments_order_id ON payments(order_id);
CREATE INDEX idx_reviews_order_id ON reviews(order_id);
