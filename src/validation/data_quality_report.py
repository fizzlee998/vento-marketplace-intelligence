"""
Data Quality Report — Vento Marketplace Intelligence Project
==================================================================
Consolidates the checks scattered across Phase 3 (initial audit), Phase 4
(cleaning verification), and Phase 6 (database load verification) into one
standing PASS/FAIL gate that runs every time the pipeline runs — not just
when someone remembers to ask for it.

Each check is a (label, fn) pair. fn returns (passed: bool, detail: str).
The script exits with code 1 if any check fails, so it can be inserted
into run_pipeline.py as a hard gate: a failed data-quality check stops the
dashboard from publishing numbers, rather than publishing wrong ones.

Run:
    python src/validation/data_quality_report.py
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "sql" / "vento_marketplace.db"
REPORT_PATH = ROOT / "reports" / "data_quality_report_latest.md"

EXPECTED_ROW_COUNTS = {
    "orders": 99441, "order_items": 112650, "customers": 93358, "sellers": 3095,
    "products": 32951, "geolocation": 19015, "payments": 103886, "reviews": 98127,
}


def check_row_counts(conn):
    problems = []
    for table, expected in EXPECTED_ROW_COUNTS.items():
        actual = pd.read_sql(f"SELECT COUNT(*) n FROM {table}", conn).iloc[0]["n"]
        if actual != expected:
            problems.append(f"{table}: expected {expected}, got {actual}")
    if problems:
        return False, "; ".join(problems)
    return True, f"All {len(EXPECTED_ROW_COUNTS)} tables match expected row counts"


def check_no_orphan_order_items(conn):
    n = pd.read_sql("""
        SELECT COUNT(*) n FROM order_items oi
        LEFT JOIN orders o ON oi.order_id = o.order_id WHERE o.order_id IS NULL
    """, conn).iloc[0]["n"]
    return n == 0, f"{n} order_items with no matching order"


def check_no_orphan_payments(conn):
    n = pd.read_sql("""
        SELECT COUNT(*) n FROM payments p
        LEFT JOIN orders o ON p.order_id = o.order_id WHERE o.order_id IS NULL
    """, conn).iloc[0]["n"]
    return n == 0, f"{n} payments with no matching order"


def check_customers_cover_all_delivered_orders(conn):
    n = pd.read_sql("""
        SELECT COUNT(*) n FROM orders o
        LEFT JOIN customers c ON o.customer_unique_id = c.customer_unique_id
        WHERE o.order_status = 'delivered' AND c.customer_unique_id IS NULL
    """, conn).iloc[0]["n"]
    return n == 0, f"{n} delivered orders with no matching customer record"

def check_no_null_product_category(conn):
    n = pd.read_sql("SELECT COUNT(*) n FROM products WHERE product_category_name_english IS NULL", conn).iloc[0]["n"]
    return n == 0, f"{n} products with a null English category (should be 'Uncategorized', never null)"


def check_geolocation_deduplicated(conn):
    n = pd.read_sql(
        "SELECT COUNT(*) n FROM geolocation GROUP BY geolocation_zip_code_prefix HAVING COUNT(*) > 1", conn
    )
    dupes = len(n)
    return dupes == 0, f"{dupes} zip-code prefixes still have duplicate geolocation rows"


def check_late_delivery_flag_is_consistent(conn):
    """is_late_delivery should exactly match delivered_date > estimated_date, recomputed independently."""
    n = pd.read_sql("""
        SELECT COUNT(*) n FROM orders
        WHERE order_status = 'delivered'
          AND (
            (is_late_delivery = 1 AND NOT (order_delivered_customer_date > order_estimated_delivery_date))
            OR
            (is_late_delivery = 0 AND (order_delivered_customer_date > order_estimated_delivery_date))
          )
    """, conn).iloc[0]["n"]
    return n == 0, f"{n} orders where is_late_delivery disagrees with a fresh recomputation"


def check_reconciliation_flag_rate_within_expected_range(conn):
    """Sanity bound: if the flagged rate ever jumps far outside the ~0.2-0.3% historically seen,
    that's worth a human look before trusting the revenue numbers downstream."""
    pct = pd.read_sql("""
        SELECT 100.0*SUM(payment_reconciliation_flag)/COUNT(*) pct FROM orders
    """, conn).iloc[0]["pct"]
    ok = pct < 2.0  # generous upper bound; current real value is ~0.26%
    return ok, f"{pct:.3f}% of orders flagged (alert threshold: 2.0%)"


def check_repeat_customer_flag_matches_order_count(conn):
    n = pd.read_sql("""
        SELECT COUNT(*) n FROM customers
        WHERE (is_repeat_customer = 1 AND n_orders <= 1) OR (is_repeat_customer = 0 AND n_orders > 1)
    """, conn).iloc[0]["n"]
    return n == 0, f"{n} customers where is_repeat_customer disagrees with their own n_orders"


CHECKS = [
    ("Row counts match expected values", check_row_counts),
    ("No orphan order_items", check_no_orphan_order_items),
    ("No orphan payments", check_no_orphan_payments),
    ("Every delivered order has a matching customer", check_customers_cover_all_delivered_orders),
    ("No null product categories", check_no_null_product_category),
    ("Geolocation fully deduplicated by zip prefix", check_geolocation_deduplicated),
    ("is_late_delivery flag is internally consistent", check_late_delivery_flag_is_consistent),
    ("Payment-reconciliation flag rate within alert threshold", check_reconciliation_flag_rate_within_expected_range),
    ("is_repeat_customer flag matches order count", check_repeat_customer_flag_matches_order_count),
]


def run():
    conn = sqlite3.connect(DB_PATH)
    results = []
    for label, fn in CHECKS:
        try:
            passed, detail = fn(conn)
        except Exception as e:
            passed, detail = False, f"Check raised an exception: {e}"
        results.append((label, passed, detail))
    conn.close()

    n_passed = sum(1 for _, p, _ in results if p)
    n_total = len(results)
    all_passed = n_passed == n_total

    lines = [
        f"# Data Quality Report — {datetime.now().isoformat(timespec='seconds')}", "",
        f"**{n_passed} of {n_total} checks passed.**", "",
        "| Check | Status | Detail |", "|---|---|---|",
    ]
    for label, passed, detail in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        lines.append(f"| {label} | {status} | {detail} |")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print(f"{n_passed}/{n_total} checks passed.")
    for label, passed, detail in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label} — {detail}")
    print(f"\nReport written to {REPORT_PATH.relative_to(ROOT)}")

    if not all_passed:
        print("\nDATA QUALITY GATE FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    run()
