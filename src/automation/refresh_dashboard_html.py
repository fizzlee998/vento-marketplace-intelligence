"""
Refresh Dashboard HTML — Vento Marketplace Intelligence Project
====================================================================
Renders dashboard/index.html from dashboard/template.html (the static
shell, never edited by automation) + the current dashboard/data.json
(refreshed each run by export_dashboard_data.py).

Kept as a separate step from export_dashboard_data.py so the template can
be redesigned independently of a data refresh, and so this step stays
idempotent — running it twice in a row produces the same index.html.

Run:
    python src/automation/refresh_dashboard_html.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT / "dashboard" / "template.html"
DATA_PATH = ROOT / "dashboard" / "data.json"
OUT_PATH = ROOT / "dashboard" / "index.html"


def run():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_json = DATA_PATH.read_text(encoding="utf-8")
    if "{DATA_JSON}" not in template:
        raise RuntimeError("template.html is missing the {DATA_JSON} placeholder — was it overwritten with rendered output?")
    rendered = template.replace("{DATA_JSON}", data_json)
    OUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    run()
