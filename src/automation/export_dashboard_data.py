"""
Export Dashboard Data — Vento Marketplace Intelligence Project
==================================================================
Runs every query the dashboard needs against sql/vento_marketplace.db and
writes the result to dashboard/data.json. This is the last step of the
automated pipeline — after this runs, dashboard/index.html can be reopened
(or redeployed) to show current numbers.

Run:
    python src/automation/export_dashboard_data.py
"""

import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "sql" / "vento_marketplace.db"
OUT_PATH = ROOT / "dashboard" / "data.json"


def q(conn, sql):
    return pd.read_sql(sql, conn)


def build_export(conn) -> dict:
    data = {}

    kpi = q(conn, """
        SELECT ROUND(SUM(order_total_value),0) total_revenue, ROUND(AVG(order_total_value),2) aov,
               COUNT(*) n_orders
        FROM orders WHERE order_status='delivered'
    """).iloc[0].to_dict()
    late = q(conn, "SELECT ROUND(100.0*SUM(is_late_delivery)/COUNT(*),1) p FROM orders WHERE order_status='delivered'").iloc[0]["p"]
    yoy = q(conn, """
        SELECT CASE WHEN order_purchase_timestamp BETWEEN '2017-02-01' AND '2017-07-31' THEN 'y2017'
                    WHEN order_purchase_timestamp BETWEEN '2018-02-01' AND '2018-07-31' THEN 'y2018' END p,
               SUM(order_total_value) rev
        FROM orders WHERE order_status='delivered'
          AND (order_purchase_timestamp BETWEEN '2017-02-01' AND '2017-07-31'
               OR order_purchase_timestamp BETWEEN '2018-02-01' AND '2018-07-31')
        GROUP BY p
    """)
    rev17 = yoy[yoy.p == "y2017"]["rev"].iloc[0]
    rev18 = yoy[yoy.p == "y2018"]["rev"].iloc[0]
    yoy_growth = round((rev18 - rev17) / rev17 * 100, 1)
    repeat_rev_pct = q(conn, """
        SELECT ROUND(100.0*SUM(CASE WHEN is_repeat_customer=1 THEN total_spent ELSE 0 END)/SUM(total_spent),1) p
        FROM customers
    """).iloc[0]["p"]

    data["kpi"] = {
        "total_revenue": kpi["total_revenue"], "aov": kpi["aov"], "n_orders": int(kpi["n_orders"]),
        "late_pct": late, "on_time_pct": round(100 - late, 1), "yoy_growth": yoy_growth,
        "repeat_rev_pct": repeat_rev_pct,
    }

    monthly = q(conn, """
        SELECT strftime('%Y-%m', order_purchase_timestamp) month, SUM(order_total_value) revenue, COUNT(*) n_orders
        FROM orders WHERE order_status='delivered' GROUP BY month HAVING n_orders > 50 ORDER BY month
    """)
    data["monthly_trend"] = {"labels": monthly["month"].tolist(),
                              "revenue": [round(x, 0) for x in monthly["revenue"]],
                              "orders": monthly["n_orders"].tolist()}

    cats = q(conn, """
        SELECT product_category_name_english cat, SUM(item_total_value) revenue
        FROM order_items GROUP BY cat ORDER BY revenue DESC LIMIT 10
    """)
    data["top_categories"] = {"labels": cats["cat"].tolist(), "revenue": [round(x, 0) for x in cats["revenue"]]}

    states = q(conn, """
        SELECT customer_state st, SUM(order_total_value) revenue FROM orders WHERE order_status='delivered'
        GROUP BY st ORDER BY revenue DESC LIMIT 10
    """)
    data["top_states_revenue"] = {"labels": states["st"].tolist(), "revenue": [round(x, 0) for x in states["revenue"]]}

    cust_split = q(conn, """
        SELECT CASE WHEN is_repeat_customer=1 THEN 'Repeat' ELSE 'One-time' END t, SUM(total_spent) rev, COUNT(*) n
        FROM customers GROUP BY t
    """)
    data["customer_split"] = {"labels": cust_split["t"].tolist(), "revenue": [round(x, 0) for x in cust_split["rev"]],
                               "n": cust_split["n"].tolist()}

    ltv_states = q(conn, """
        SELECT primary_state st, AVG(total_spent) ltv FROM customers GROUP BY st HAVING COUNT(*)>=100
        ORDER BY ltv DESC LIMIT 8
    """)
    data["top_ltv_states"] = {"labels": ltv_states["st"].tolist(), "ltv": [round(x, 2) for x in ltv_states["ltv"]]}

    bins = q(conn, """
        SELECT CASE WHEN days_to_deliver<=5 THEN '0-5' WHEN days_to_deliver<=10 THEN '6-10'
                     WHEN days_to_deliver<=15 THEN '11-15' WHEN days_to_deliver<=20 THEN '16-20'
                     WHEN days_to_deliver<=30 THEN '21-30' ELSE '30+' END bucket, COUNT(*) n
        FROM orders WHERE order_status='delivered' AND days_to_deliver IS NOT NULL GROUP BY bucket
    """)
    order_map = {"0-5": 0, "6-10": 1, "11-15": 2, "16-20": 3, "21-30": 4, "30+": 5}
    bins = bins.sort_values("bucket", key=lambda s: s.map(order_map))
    data["delivery_time_bins"] = {"labels": bins["bucket"].tolist(), "n": bins["n"].tolist()}

    state_late = q(conn, """
        SELECT customer_state st, ROUND(100.0*SUM(is_late_delivery)/COUNT(*),1) late_pct, COUNT(*) n
        FROM orders WHERE order_status='delivered' GROUP BY st HAVING n>=200 ORDER BY late_pct DESC LIMIT 8
    """)
    data["worst_late_states"] = {"labels": state_late["st"].tolist(), "late_pct": state_late["late_pct"].tolist()}

    seller_risk = q(conn, """
        SELECT seller_id, n_orders, ROUND(late_delivery_rate*100,1) late_rate, ROUND(avg_review_score,2) avg_score,
               ROUND(late_delivery_rate * (5-avg_review_score),3) risk_score
        FROM sellers WHERE n_orders>=15 ORDER BY risk_score DESC LIMIT 8
    """)
    data["seller_risk_table"] = seller_risk.to_dict(orient="records")

    review_by_late = q(conn, """
        SELECT is_late_delivery, ROUND(AVG(review_score),2) avg_score FROM orders
        WHERE order_status='delivered' AND review_score IS NOT NULL GROUP BY is_late_delivery
    """)
    data["review_by_late"] = {
        "on_time": float(review_by_late[review_by_late.is_late_delivery == 0]["avg_score"].iloc[0]),
        "late": float(review_by_late[review_by_late.is_late_delivery == 1]["avg_score"].iloc[0]),
    }

    pay_mix = q(conn, """
        SELECT primary_payment_type t, SUM(order_total_value) revenue, COUNT(*) n, AVG(order_total_value) aov
        FROM orders WHERE order_status='delivered' AND primary_payment_type IS NOT NULL GROUP BY t ORDER BY revenue DESC
    """)
    data["payment_mix"] = {"labels": pay_mix["t"].tolist(), "revenue": [round(x, 0) for x in pay_mix["revenue"]],
                            "n": pay_mix["n"].tolist(), "aov": [round(x, 2) for x in pay_mix["aov"]]}

    installments = q(conn, """
        SELECT max_installments inst, ROUND(AVG(order_total_value),2) aov, COUNT(*) n
        FROM orders WHERE order_status='delivered' AND primary_payment_type='credit_card'
          AND max_installments BETWEEN 1 AND 10
        GROUP BY inst ORDER BY inst
    """)
    data["installments_aov"] = {"labels": [str(x) for x in installments["inst"]], "aov": installments["aov"].tolist()}

    recon = q(conn, """
        SELECT primary_payment_type t, ROUND(100.0*SUM(payment_reconciliation_flag)/COUNT(*),3) pct
        FROM orders WHERE primary_payment_type IS NOT NULL GROUP BY t ORDER BY pct DESC
    """)
    data["reconciliation_by_payment"] = {"labels": recon["t"].tolist(), "pct": recon["pct"].tolist()}

    spend = q(conn, """
        SELECT o.month, revenue, spend FROM (
          SELECT strftime('%Y-%m', order_purchase_timestamp) month, SUM(order_total_value) revenue
          FROM orders WHERE order_status='delivered' GROUP BY month
        ) o JOIN (SELECT month, SUM(spend_brl) spend FROM marketing_spend_synthetic GROUP BY month) m
          ON o.month = m.month
        ORDER BY o.month
    """)
    data["marketing_vs_revenue"] = {"labels": spend["month"].tolist(),
                                     "revenue": [round(x, 0) for x in spend["revenue"]],
                                     "spend": [round(x, 0) for x in spend["spend"]]}
    return data


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    data = build_export(conn)
    conn.close()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")
    print("NOTE: dashboard/index.html embeds this data at build time.")
    print("Re-run src/automation/refresh_dashboard_html.py after this to push the new numbers into index.html.")
