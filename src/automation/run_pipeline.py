"""
Run Pipeline — Vento Marketplace Intelligence Project
==========================================================
The single command that replaces the ops manager's manual Monday routine:

    raw client Excel exports
        -> clean
        -> transform (marts)
        -> load database
        -> export dashboard data
        -> render dashboard HTML

Each step is a script that already runs standalone (for debugging); this
just calls them in order, times each one, stops on the first failure, and
writes a timestamped run log to reports/pipeline_runs/.

Run:
    python src/automation/run_pipeline.py
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "reports" / "pipeline_runs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

STEPS = [
    ("Clean raw client exports", "src/cleaning/clean_pipeline.py"),
    ("Build analytical marts", "src/transformation/build_marts.py"),
    ("Load SQL database", "src/database/build_database.py"),
    ("Data quality gate", "src/validation/data_quality_report.py"),
    ("Export dashboard data", "src/automation/export_dashboard_data.py"),
    ("Refresh dashboard HTML", "src/automation/refresh_dashboard_html.py"),
]


def run():
    run_started = datetime.now()
    log_lines = [f"# Pipeline run — {run_started.isoformat(timespec='seconds')}", ""]
    total_start = time.time()

    for label, script in STEPS:
        print(f"\n=== {label} ({script}) ===")
        step_start = time.time()
        result = subprocess.run(
            [sys.executable, str(ROOT / script)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        elapsed = time.time() - step_start

        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            log_lines.append(f"- **{label}** — FAILED after {elapsed:.1f}s")
            log_lines.append(f"  ```\n{result.stderr.strip()[-1500:]}\n  ```")
            (LOG_DIR / f"{run_started.strftime('%Y%m%d_%H%M%S')}.md").write_text("\n".join(log_lines), encoding="utf-8")
            print(f"\nPipeline stopped: {label} failed after {elapsed:.1f}s.")
            sys.exit(1)

        print(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)")
        log_lines.append(f"- **{label}** — OK in {elapsed:.1f}s")

    total_elapsed = time.time() - total_start
    log_lines.append(f"\n**Total run time: {total_elapsed:.1f}s**")
    log_path = LOG_DIR / f"{run_started.strftime('%Y%m%d_%H%M%S')}.md"
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"Pipeline complete in {total_elapsed:.1f}s.")
    print(f"Run log: {log_path.relative_to(ROOT)}")
    print("Dashboard is up to date: dashboard/index.html")


if __name__ == "__main__":
    run()
