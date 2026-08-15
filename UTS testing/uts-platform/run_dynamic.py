"""
Dynamic test runner — only URL + username + password required.

1. Discovers UI from the URL (login fields, links, forms)
2. Runs Selenium automation dynamically (automation scenarios only)
3. Creates HTML report
4. Exports Xpedite format (TC/BPW/BC XML + TestData.xlsx) — automation only
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
from automation.selenium_session import get_driver, quit_driver, shutdown_all, start_browser
from dynamic.automation_runner import run_all_automation, save_discovery
from dynamic.discovery import discover_application
from report_generator import write_html_report
from xpedite.exporter import export_discovery_to_xpedite

CONFIG_DIR = ROOT / "config"
INPUT_FILE = CONFIG_DIR / "app-input.json"
REPORTS_DIR = ROOT / "reports"


def load_input() -> dict:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Create {INPUT_FILE} with url, username, password")
    data = json.loads(INPUT_FILE.read_text(encoding="utf-8-sig"))
    for field in ("url", "username", "password"):
        if not data.get(field):
            raise ValueError(f"app-input.json missing required field: {field}")
    return data


def print_header(app_name: str, url: str):
    print()
    print("=" * 64)
    print("  UTS DYNAMIC TEST AUTOMATION")
    print(f"  App: {app_name}")
    print(f"  URL: {url}")
    print("=" * 64)
    print()


def main() -> int:
    started = time.perf_counter()
    inp = load_input()
    url = inp["url"].strip()
    username = inp["username"]
    password = inp["password"]
    app_name = inp.get("app_name") or url.split("//")[-1].split("/")[0]
    description = (inp.get("description") or "").strip()
    role_hint = (inp.get("role") or "").strip()

    print_header(app_name, url)
    if description:
        print(f"  Description / module focus: {description}")
    else:
        print("  Description: (empty) — complete application flow")
    exit_code = 0

    try:
        # Phase 1: Discover UI from URL
        print("[1/4] DISCOVER — scanning URL for login, links, forms...")
        print("-" * 64)
        start_browser(url)
        discovery = discover_application(
            get_driver(), url, username, password, app_name,
            automation_only=True, description=description, role_hint=role_hint,
        )
        flow_path = save_discovery(discovery)
        auto_count = sum(1 for s in discovery.scenarios if s.type == "automation")
        print(f"  Page title: {discovery.page_title}")
        print(f"  Login URL:  {discovery.login_url}")
        print(f"  After login: {discovery.post_login_url}")
        print(f"  Locators:   {len(discovery.locators)} elements found")
        print(f"  Automation: {auto_count} test cases (manual skipped)")
        print(f"  Saved:      {flow_path}")
        print()

        quit_driver()

        # Phase 2: Xpedite export (automation only)
        print("[2/4] XPEDITE — generating automated TC/BPW/BC + TestData.xlsx...")
        print("-" * 64)
        xpedite_out = export_discovery_to_xpedite(discovery, password)
        print(f"  Output: {xpedite_out}")
        print(f"  RowNum starts from 2 | Manual TCs NOT exported")
        print()

        # Phase 3: Run dynamic automation
        print("[3/4] AUTOMATION — running Selenium (no halt on fail)...")
        print("-" * 64)
        start_browser(url)
        logger = ExecutionLogger("dynamic-run")
        logger.info(f"Dynamic run for {url}")
        automation_results = run_all_automation(
            discovery, password, logger, logout_after_each=True, continue_on_failure=True,
            role_hint=role_hint,
        )
        for r in automation_results:
            print(f"  {r.tc_id}: {r.status}")
        print()

        total_ms = (time.perf_counter() - started) * 1000
        passed = sum(1 for r in automation_results if r.status == "PASS")
        failed = sum(1 for r in automation_results if r.status == "FAIL")

        # Phase 4: Report
        print("[4/4] REPORT — generating HTML...")
        print("-" * 64)
        report_path = write_html_report(
            automation_results=automation_results,
            manual_scenarios=[],
            execution_log=logger.content,
            suite_name=f"Dynamic — {app_name}",
            environment=url,
            total_duration_ms=total_ms,
            show_execution_log=inp.get("show_execution_log_in_report", False),
        )
        latest = REPORTS_DIR / "latest-e2e-report.html"
        print(f"  Report: {report_path}")
        print(f"  Latest: {latest}")
        print()

        print("=" * 64)
        print("  COMPLETE")
        print(f"  URL:       {url}")
        print(f"  Auto:      {passed}/{len(automation_results)} passed")
        print(f"  Xpedite:   {xpedite_out}")
        print(f"  Time:      {total_ms/1000:.2f}s")
        print("=" * 64)

        webbrowser.open(latest.resolve().as_uri())
        exit_code = 1 if failed else 0

    finally:
        shutdown_all()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
