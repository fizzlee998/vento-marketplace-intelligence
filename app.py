"""
Vento Weekly Report — Manager Interface
===========================================
The actual thing a non-technical ops manager would use: a web page with an
upload box per source file and a "Run" button. Everything underneath is
the exact same pipeline built in Phases 4-12 — this is just a front door
on top of it, so nobody has to open a terminal.

Run:
    streamlit run app.py

Then open the URL it prints (usually http://localhost:8501) in a browser.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
EXPORTS_DIR = ROOT / "data" / "raw" / "client_excel_exports"
DASHBOARD_PATH = ROOT / "dashboard" / "index.html"
QUALITY_REPORT_PATH = ROOT / "reports" / "data_quality_report_latest.md"

EXPECTED_FILES = {
    "01_order_system_export.xlsx": "Order system export (Orders + Customers)",
    "02_payments_processor_export.xlsx": "Payments processor export",
    "03_logistics_partner_export.xlsx": "Logistics partner export (Items + Sellers)",
    "04_customer_reviews_export.xlsx": "Customer reviews export",
    "05_product_catalog_export.xlsx": "Product catalog export",
    "06_marketing_spend_export_SYNTHETIC.xlsx": "Marketing spend (synthetic)",
}

PIPELINE_STEPS = [
    ("Cleaning the data", "src/cleaning/clean_pipeline.py"),
    ("Building the analysis tables", "src/transformation/build_marts.py"),
    ("Loading the database", "src/database/build_database.py"),
    ("Running data-quality checks", "src/validation/data_quality_report.py"),
    ("Preparing dashboard numbers", "src/automation/export_dashboard_data.py"),
    ("Refreshing the dashboard", "src/automation/refresh_dashboard_html.py"),
]

st.set_page_config(page_title="Vento Weekly Report", layout="wide")
st.title("Vento — Weekly Report Automation")
st.caption("Upload this week's files from each department below, then click Run.")

st.divider()
st.subheader("1. Upload this week's files")

uploads = {}
missing = []
for filename, label in EXPECTED_FILES.items():
    uploaded = st.file_uploader(label, type=["xlsx"], key=filename)
    if uploaded is not None:
        uploads[filename] = uploaded
    else:
        missing.append(label)

existing_files = {f.name for f in EXPORTS_DIR.glob("*.xlsx")} if EXPORTS_DIR.exists() else set()
if missing and existing_files:
    st.info(
        f"{len(missing)} file(s) not uploaded this run — last week's copy will be reused for those "
        f"if present. Upload a file here whenever you want to replace it."
    )

st.divider()
st.subheader("2. Run")

run_clicked = st.button("Run this week's report", type="primary")

if run_clicked:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    for filename, uploaded_file in uploads.items():
        target = EXPORTS_DIR / filename
        target.write_bytes(uploaded_file.getbuffer())

    still_missing = [EXPECTED_FILES[f] for f in EXPECTED_FILES if not (EXPORTS_DIR / f).exists()]
    if still_missing:
        st.error("Cannot run — these files have never been uploaded and there's no previous copy:\n\n"
                  + "\n".join(f"- {m}" for m in still_missing))
        st.stop()

    progress = st.progress(0, text="Starting...")
    log_area = st.empty()
    log_lines = []

    failed = False
    for i, (label, script) in enumerate(PIPELINE_STEPS):
        progress.progress(i / len(PIPELINE_STEPS), text=label)
        result = subprocess.run(
            [sys.executable, str(ROOT / script)], cwd=str(ROOT), capture_output=True, text=True,
        )
        if result.returncode != 0:
            log_lines.append(f"FAILED — {label}")
            log_area.code("\n".join(log_lines) + "\n\n" + result.stderr[-2000:])
            st.error(f"Stopped at: {label}. See the error above.")
            failed = True
            break
        log_lines.append(f"Done — {label}")
        log_area.code("\n".join(log_lines))

    if not failed:
        progress.progress(1.0, text="Complete")
        st.success("This week's report is ready.")

st.divider()
st.subheader("3. This week's results")

if QUALITY_REPORT_PATH.exists():
    quality_text = QUALITY_REPORT_PATH.read_text(encoding="utf-8")
    if "checks passed" in quality_text:
        first_line = [l for l in quality_text.splitlines() if "checks passed" in l][0]
        if quality_text.count("PASS") and "FAIL" not in quality_text:
            st.success(f"Data quality: {first_line.strip('*')}")
        else:
            st.warning(f"Data quality: {first_line.strip('*')} — see reports/data_quality_report_latest.md for details")

if DASHBOARD_PATH.exists():
    st.markdown(f"**Dashboard file:** `{DASHBOARD_PATH}`")
    with st.expander("View dashboard here", expanded=False):
        st.components.v1.html(DASHBOARD_PATH.read_text(encoding="utf-8"), height=900, scrolling=True)
else:
    st.caption("No dashboard yet — run the report above first.")
