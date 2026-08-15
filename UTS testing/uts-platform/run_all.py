"""
UTS Test Automation Suite — one-click runner.
Manual tests + Selenium automation + HTML report + browser step display.
"""

from __future__ import annotations

import json
import os
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from automation.base import ExecutionLogger
from automation.selenium_session import quit_driver, shutdown_all
from automation.test_login import run as run_login
from automation.test_navigation import run as run_navigation
from automation.test_transfer import run as run_transfer
from report_generator import write_html_report

CONFIG_DIR = ROOT / "config"
MANUAL_DIR = ROOT / "manual-tests"
REPORTS_DIR = ROOT / "reports"


def load_scenarios() -> dict:
    return json.loads((CONFIG_DIR / "scenarios.json").read_text(encoding="utf-8"))


def print_header():
    print()
    print("=" * 64)
    print("  UTS TEST AUTOMATION SUITE")
    print("  Manual + Selenium | Steps shown LIVE in browser")
    print("=" * 64)
    print()


def run_manual_phase(manual: list[dict], open_files: bool = True) -> None:
    print("[1/3] MANUAL TEST CASES")
    print("-" * 64)
    for s in manual:
        path = ROOT / s["file"]
        print(f"  {s['id']}: {s['title']}")
        print(f"    -> {path}")
        if open_files and path.exists():
            os.startfile(str(path))  # noqa: S606
    print()
    print(f"  Manual folder: {MANUAL_DIR}")
    if open_files:
        os.startfile(str(MANUAL_DIR))  # noqa: S606
    print()


def run_automation_phase(logger: ExecutionLogger) -> list:
    print("[2/3] SELENIUM AUTOMATION — 3 scenarios")
    print("-" * 64)

    runners = [
        ("TC_AUTO_01", "Login validation", run_login),
        ("TC_AUTO_02", "Navigation to transfer", run_navigation),
        ("TC_AUTO_03", "Transfer E2E flow", run_transfer),
    ]

    results = []
    for tc_id, label, runner in runners:
        logger.executing(f"Starting {tc_id}: {label}")
        result = runner(logger)
        results.append(result)
        print(f"  {tc_id}: {result.status}")
    print()
    return results


def run_report_phase(
    automation_results: list,
    manual: list[dict],
    logger: ExecutionLogger,
    suite_name: str,
    duration_ms: float,
) -> Path:
    print("[3/3] HTML REPORT")
    print("-" * 64)

    test_data = json.loads((CONFIG_DIR / "test-data.json").read_text(encoding="utf-8"))
    report_path = write_html_report(
        automation_results=automation_results,
        manual_scenarios=manual,
        execution_log=logger.content,
        suite_name=suite_name,
        environment=test_data.get("environment", "DevEnv"),
        total_duration_ms=duration_ms,
    )
    latest = REPORTS_DIR / "latest-e2e-report.html"
    print(f"  Report: {report_path}")
    print(f"  Latest: {latest}")
    return latest


def open_report(path: Path) -> None:
    url = path.resolve().as_uri()
    webbrowser.open(url)
    print(f"  Opened in browser: {url}")


def main() -> int:
    started = time.perf_counter()
    print_header()
    exit_code = 0

    try:
        config = load_scenarios()
        manual = [s for s in config["scenarios"] if s["type"] == "manual"]

        run_manual_phase(manual, open_files=True)

        logger = ExecutionLogger("one-click-run")
        logger.info("UTS Test Automation Suite started (Selenium)")
        automation_results = run_automation_phase(logger)

        total_ms = (time.perf_counter() - started) * 1000
        passed = sum(1 for r in automation_results if r.status == "PASS")
        failed = sum(1 for r in automation_results if r.status == "FAIL")

        latest_report = run_report_phase(
            automation_results, manual, logger, config["suite_name"], total_ms
        )

        print()
        print("=" * 64)
        print("  COMPLETE")
        print(f"  Folder:  {ROOT}")
        print(f"  Manual:  {len(manual)} test cases opened")
        print(f"  Auto:    {passed}/3 passed, {failed}/3 failed")
        print(f"  Time:    {total_ms/1000:.2f}s")
        print(f"  Log:     {logger.log_path}")
        print("=" * 64)
        print()

        open_report(latest_report)
        exit_code = 1 if failed else 0
    finally:
        shutdown_all()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
