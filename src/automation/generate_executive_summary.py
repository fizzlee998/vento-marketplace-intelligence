"""
Generate Executive Summary — Vento Marketplace Intelligence Project
========================================================================
Calls Claude to write a short weekly executive summary — but only ever
hands it the validated numbers already sitting in dashboard/data.json
(the same numbers that drive the dashboard). It never sees raw order
rows, so it cannot "discover" a number that isn't already verified.

After generation, validate_summary() re-extracts every number the model
wrote and checks it against the source data. Anything that doesn't match
is flagged for human review rather than sent out silently — this is the
concrete answer to "how do you stop the AI from inventing facts."

Requires an Anthropic API key in the ANTHROPIC_API_KEY environment
variable. If it's not set, the script prints the exact prompt it would
have sent and exits — useful for reviewing/tuning the prompt without
spending API calls.

Run:
    export ANTHROPIC_API_KEY=sk-...
    python src/automation/generate_executive_summary.py
"""

import json
import os
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "dashboard" / "data.json"
OUT_PATH = ROOT / "reports" / "executive_summary_latest.md"

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are writing a short weekly executive summary for the leadership of \
Vento Marketplace, a mid-size e-commerce marketplace operator.

STRICT RULES:
1. Use ONLY the numbers given to you in the KPI data below. Do not calculate, estimate, \
round, or infer any number that is not directly present in the data.
2. If you want to make a comparison (e.g. "up from last month"), only do so if both values \
are explicitly present in the data.
3. Do not invent seller names, customer names, or specific dates not present in the data.
4. Write 150-200 words, plain business prose, no markdown headers or bullet lists.
5. Lead with the single most decision-relevant finding, not just the biggest number.
"""


def load_kpi_context() -> dict:
    """Only the KPI-level data — never raw order/customer rows — is exposed to the model."""
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    # Deliberately curated subset: KPIs + top-line aggregates only, no PII, no row-level data.
    context = {
        "executive_kpis": data["kpi"],
        "monthly_trend_last_3_months": {
            "labels": data["monthly_trend"]["labels"][-3:],
            "revenue": data["monthly_trend"]["revenue"][-3:],
        },
        "top_3_categories_by_revenue": {
            "labels": data["top_categories"]["labels"][:3],
            "revenue": data["top_categories"]["revenue"][:3],
        },
        "review_score_by_delivery_timeliness": data["review_by_late"],
        "worst_late_delivery_states_top_3": {
            "labels": data["worst_late_states"]["labels"][:3],
            "late_pct": data["worst_late_states"]["late_pct"][:3],
        },
        "highest_risk_seller": data["seller_risk_table"][0] if data["seller_risk_table"] else None,
    }
    return context


def call_claude(context: dict) -> str:
    import anthropic  # imported here so the script still runs (in dry-run mode) without the package installed

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    message = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Here is this week's validated KPI data:\n\n{json.dumps(context, indent=2)}\n\n"
                       f"Write the executive summary.",
        }],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def extract_numbers(text: str) -> list:
    """Pull every numeric token out of the summary, normalized for comparison."""
    raw = re.findall(r'-?\d[\d,]*\.?\d*%?', text)
    cleaned = []
    for tok in raw:
        t = tok.replace(",", "").rstrip("%")
        try:
            cleaned.append(float(t))
        except ValueError:
            continue
    return cleaned


def flatten_source_numbers(context: dict) -> set:
    """Every number that legitimately appears anywhere in the context the model was given."""
    found = set()

    def walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, (int, float)):
            found.add(round(float(obj), 2))
            found.add(round(float(obj)))  # also allow the rounded/whole-number form

    walk(context)
    return found


def validate_summary(text: str, context: dict, tolerance: float = 0.5) -> dict:
    """Flags any number in the summary that isn't traceable (within tolerance) to the source data."""
    summary_numbers = extract_numbers(text)
    source_numbers = flatten_source_numbers(context)

    unverified = []
    for n in summary_numbers:
        if n in (100, 0, 1):  # common non-data numbers ("100%", "a single", etc.) — not worth flagging
            continue
        if not any(abs(n - s) <= tolerance for s in source_numbers):
            unverified.append(n)

    return {
        "n_numbers_in_summary": len(summary_numbers),
        "n_unverified": len(unverified),
        "unverified_numbers": unverified,
        "passed": len(unverified) == 0,
    }


def run():
    context = load_kpi_context()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — dry run. Here is exactly what would be sent:\n")
        print("SYSTEM PROMPT:\n" + SYSTEM_PROMPT)
        print("\nKPI CONTEXT SENT TO THE MODEL:\n" + json.dumps(context, indent=2))
        return

    summary = call_claude(context)
    validation = validate_summary(summary, context)

    report = [
        f"# Executive Summary — {date.today().isoformat()}", "",
        summary, "",
        "---", "",
        f"**Validation:** {validation['n_numbers_in_summary']} numbers found in the summary, "
        f"{validation['n_unverified']} unverified against source data.",
    ]
    if not validation["passed"]:
        report.append(f"**⚠ Review required before sending** — unverified figures: {validation['unverified_numbers']}")
    else:
        report.append("**✓ All figures verified against dashboard/data.json.**")

    OUT_PATH.write_text("\n".join(report), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(f"Validation: {'PASSED' if validation['passed'] else 'FAILED — see report'}")


if __name__ == "__main__":
    run()
