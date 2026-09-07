"""
UTS E2E Test Suite Runner
- 2 Manual test cases (documented, pending human execution)
- 3 Automation test cases (executed with live logging)
- HTML report with execution details
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from automation.base import ExecutionLogger, TestResult
from automation.test_login import run as run_login
from automation.test_navigation import run as run_navigation
from automation.test_transfer import run as run_transfer
from automation.selenium_session import quit_driver, shutdown_all
from report_generator import write_html_report

CONFIG_DIR = ROOT / "config"


def load_scenarios() -> dict:
    return json.loads((CONFIG_DIR / "scenarios.json").read_text(encoding="utf-8"))


def print_banner():
    print()
    print("=" * 62)
    print("  UTS E2E TEST SUITE")
    print("  5 Scenarios: 2 Manual + 3 Automation")
    print("=" * 62)
    print()


def run_automation_suite(logger: ExecutionLogger) -> list[TestResult]:
    from automation.session_reset import prepare_static_fresh_session, teardown_static

    results: list[TestResult] = []

    runners = [
        ("TC_AUTO_01", "Login validation", run_login),
        ("TC_AUTO_02", "Navigation to transfer", run_navigation),
        ("TC_AUTO_03", "Transfer E2E flow", run_transfer),
    ]

    for tc_id, label, runner in runners:
        logger.info("")
        logger.executing(f"Starting {tc_id}: {label}")

        if tc_id != "TC_AUTO_01":
            logger.info(f"{tc_id}: fresh login before scenario")
            prepare_static_fresh_session(logger)

        try:
            result = runner(logger)
            results.append(result)
            logger.info(f"Completed {tc_id} => {result.status}")
            if result.status == "FAIL":
                logger.info(f"{tc_id} failed — continuing to next test (no halt)")
        except Exception as exc:  # noqa: BLE001
            logger.fail(f"{tc_id} crashed: {exc}")
            results.append(
                TestResult(
                    tc_id=tc_id,
                    title=label,
                    test_type="automation",
                    status="FAIL",
                    error=str(exc),
                )
            )
        finally:
            logger.info(f"{tc_id}: logout after test — clean session for next scenario")
            teardown_static(logger=logger)

    return results


def main() -> int:
    started = time.perf_counter()
    print_banner()

    config = load_scenarios()
    manual = [s for s in config["scenarios"] if s["type"] == "manual"]
    exit_code = 0

    try:
        print("[MANUAL] 2 test cases ready for human execution:")
        for s in manual:
            print(f"  - {s['id']}: {s['title']}")
            print(f"    File: {ROOT / s['file']}")
        print()

        logger = ExecutionLogger("e2e-automation")
        logger.info("E2E Automation run started (Selenium WebDriver)")
        logger.info(f"Suite: {config['suite_name']}")
        logger.executing("Automation engine initialized — running 3 Selenium scenarios")

        print("[AUTOMATION] Executing 3 Selenium scenarios...")
        print("[AUTOMATION] Live execution log (what is running now):")
        print("-" * 62)

        automation_results = run_automation_suite(logger)

        print("-" * 62)
        total_ms = (time.perf_counter() - started) * 1000

        passed = sum(1 for r in automation_results if r.status == "PASS")
        failed = sum(1 for r in automation_results if r.status == "FAIL")

        print()
        print("AUTOMATION SUMMARY")
        print(f"  Passed: {passed}/3")
        print(f"  Failed: {failed}/3")
        print(f"  Duration: {total_ms/1000:.2f}s")
        print(f"  Execution log: {logger.log_path}")

        test_data = json.loads((CONFIG_DIR / "test-data.json").read_text(encoding="utf-8"))
        report_path = write_html_report(
            automation_results=automation_results,
            manual_scenarios=manual,
            execution_log=logger.content,
            suite_name=config["suite_name"],
            environment=test_data.get("environment", "DevEnv"),
            total_duration_ms=total_ms,
        )

        print()
        print("REPORT GENERATED")
        print(f"  HTML: {report_path}")
        print(f"  Latest: {ROOT / 'reports' / 'latest-e2e-report.html'}")
        print()

        exit_code = 1 if failed else 0
    finally:
        shutdown_all()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
