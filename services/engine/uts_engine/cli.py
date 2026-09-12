"""
UTS Automation — full story

START → app-input.json me module name check karo
  |
  |-- Module name NAHI hai:
  |     → website scan karo
  |     → saare modules generated/modules.json me daalo
  |     → STOP (test case nahi banega)
  |
  |-- Module name HAI (e.g. "module": "Admin"):
        → modules.json me check karo ke ye module exist karta hai
        → agar modules.json nahi hai to pehle scan karke bana lo
        → module mila → us module ke test cases banao + Xpedite + run
        → module nahi mila → error, list dikhao
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import webbrowser
from pathlib import Path
from typing import Callable

# Windows console often uses cp1252 — avoid crash on Unicode arrows/dashes in print()
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

# services/engine/, one level above uts_engine/ — kept on sys.path so this still
# works whether invoked as `python -m uts_engine.cli` or as a bare script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from uts_engine.automation.base import ExecutionLogger
from uts_engine.automation.selenium_session import (
    get_driver,
    has_session,
    quit_driver,
    shutdown_all,
    start_browser,
)
from uts_engine.discovery.automation_runner import run_all_automation, save_discovery
from uts_engine.discovery.discovery import AUTOMATION_TYPES, discover_application
from uts_engine.discovery.module_selector import (
    build_modules_catalog,
    load_modules_catalog,
    modules_catalog_exists,
    print_module_menu,
    save_modules_catalog,
)
from uts_engine.exporters.report_generator import write_html_report
from uts_engine.exporters.selenium_script_generator import generate_selenium_from_discovery
from uts_engine.discovery.common_actions import save_actions_catalog
from uts_engine.exporters.alm.exporter import export_discovery_to_alm, export_modules_catalog_to_alm
from uts_engine.exporters.xpedite.exporter import export_discovery_to_xpedite
from uts_engine.workdir import data_root

CONFIG_DIR = ROOT / "config"
INPUT_FILE = CONFIG_DIR / "app-input.json"
REPORTS_DIR = data_root() / "reports"


def load_input() -> dict:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Create {INPUT_FILE} with url, username, password")
    data = json.loads(INPUT_FILE.read_text(encoding="utf-8-sig"))
    for field in ("url", "username", "password"):
        if not data.get(field):
            raise ValueError(f"app-input.json missing required field: {field}")
    return data


def _split_modules(text: str) -> list[str]:
    """Split module names by # (also , ; | for convenience)."""
    parts = re.split(r"[#,;|]+", text or "")
    return [p.strip() for p in parts if p.strip()]


def get_module_names_from_input(inp: dict) -> list[str]:
    """
    app-input.json me module name(s).
    Ek se zyada module ke liye '#' se separate karo:
      "module": "Admin#PIM#Leave"
    List bhi de sakte ho:
      "module": ["Admin", "PIM"]
    """
    raw = inp.get("module")
    if isinstance(raw, str) and raw.strip():
        return _split_modules(raw)
    if isinstance(raw, list) and raw:
        out: list[str] = []
        for x in raw:
            out.extend(_split_modules(str(x)))
        return out

    raw = inp.get("selected_modules")
    if isinstance(raw, list) and raw:
        out = []
        for x in raw:
            out.extend(_split_modules(str(x)))
        return out
    if isinstance(raw, str) and raw.strip():
        return _split_modules(raw)

    return []


def scan_modules_to_json(inp: dict):
    """Cycle 1: Open URL -> Login -> Scan modules -> Save modules.json -> STOP (no TCs)."""
    url = inp["url"].strip()
    username = inp["username"]
    password = inp["password"]
    app_name = inp.get("app_name") or url.split("//")[-1].split("/")[0]
    role_hint = (inp.get("role") or "").strip()

    print("  CYCLE 1: SCAN MODULES ONLY")
    print("  Login -> list all modules -> save modules.json -> STOP")
    print("  (Test cases create nahi honge — Cycle 2 me selected module ke liye banenge)")
    print("-" * 68)
    start_browser(url)
    discovery = discover_application(
        get_driver(),
        url,
        username,
        password,
        app_name,
        automation_only=True,
        description="",
        role_hint=role_hint,
        list_modules_only=True,
    )
    modules = discovery.modules or build_modules_catalog(discovery)
    cat_path = save_modules_catalog(modules, app_name=app_name, url=url)
    actions_path = save_actions_catalog()
    save_discovery(discovery)
    alm_out = export_modules_catalog_to_alm(modules, app_name=app_name, url=url)
    if not has_session():
        quit_driver()

    print()
    print(f"  Modules scanned: {len(modules)}")
    print_module_menu(modules)
    print(f"  Saved: {cat_path}")
    print(f"  Common actions: {actions_path}")
    print(f"  ALM catalog: {alm_out}")
    print()
    print("  *** NO TEST CASES CREATED IN CYCLE 1 ***")
    print()
    return modules


def match_modules(wanted: list[str], catalog: list[dict]) -> tuple[list[str], list[str]]:
    """Return (found_names, not_found)."""
    found, missing = [], []
    for w in wanted:
        hit = None
        for m in catalog:
            if m["name"].lower() == w.lower():
                hit = m["name"]
                break
        if not hit:
            hit = next((m["name"] for m in catalog if w.lower() in m["name"].lower()), None)
        if hit and hit not in found:
            found.append(hit)
        elif not hit:
            missing.append(w)
    return found, missing


def create_and_run(
    inp: dict,
    selected: list[str],
    run_tests: bool = False,
    open_outputs: bool = True,
    selected_test_case_ids: list[str] | None = None,
    on_step_progress: Callable[[str], None] | None = None,
) -> int:
    """Cycle 2: Create test cases for selected module(s) + ALM + Xpedite.
    Automation runs ONLY when run_tests=True ("run_automation": true in config)."""
    url = inp["url"].strip()
    username = inp["username"]
    password = inp["password"]
    app_name = inp.get("app_name") or url.split("//")[-1].split("/")[0]
    role_hint = (inp.get("role") or "").strip()
    logout_after_each = inp.get("logout_after_each_test", True)
    started = time.perf_counter()

    use_ai = bool(inp.get("ai_mode") or inp.get("use_ai"))
    print(f"  CYCLE 2: CREATE TEST CASES for: {', '.join(selected)}")
    if use_ai:
        print("  AI MODE: understand app → objects / link / enter / verify / data-driven / BDD")
    print("  1) Understand selected module pages")
    print("  2) Create test cases (Search/Add/Fill/Save/Verify)")
    print("  3) Export ALM + Xpedite")
    if run_tests:
        print("  4) Run automation  (run_automation: true)")
    else:
        print("  4) Automation SKIPPED (run_automation: false — sirf TCs banenge)")
    save_actions_catalog()
    print("-" * 68)
    start_browser(url)
    discovery = discover_application(
        get_driver(),
        url,
        username,
        password,
        app_name,
        automation_only=True,
        description="",
        role_hint=role_hint,
        list_modules_only=False,
        selected_modules=selected,
    )

    if use_ai:
        from uts_engine.planning.ai_pipeline import apply_ai_plan_to_discovery

        page_map_path = data_root() / "generated" / "page-map.json"
        page_map = {}
        if page_map_path.is_file():
            page_map = json.loads(page_map_path.read_text(encoding="utf-8-sig"))
        print()
        print("  AI BRAIN — understanding application flows...")
        plan = apply_ai_plan_to_discovery(
            discovery,
            page_map=page_map,
            modules=selected,
            username=username,
            replace_scenarios=True,
        )
        print(f"  AI: {plan.get('summary')}")
        print(f"  AI provider: {plan.get('provider')}")
        print(f"  Concepts: {', '.join(plan.get('concepts_covered') or [])}")
        print(f"  Objects:  {len(plan.get('objects') or [])}")
        print(f"  BDD:      generated/bdd/*.feature")
        print(f"  Data:     generated/AI_TestData.xlsx (if data-driven rows exist)")
        print()

    flow_path = save_discovery(discovery)

    selenium_dir = data_root() / "generated" / "selenium_automation"
    selenium_paths = generate_selenium_from_discovery(discovery, selenium_dir)
    print(f"  Selenium scripts: {len(selenium_paths)} file(s) in {selenium_dir}")

    auto = [s for s in discovery.scenarios if s.type in AUTOMATION_TYPES]
    print(f"  Test cases created: {len(auto)}")
    for s in auto:
        tag = f"[{s.module}] " if s.module else ""
        print(f"    - {s.id}: {tag}{s.title}")
    print(f"  Saved: {flow_path}")
    print()
    # Closing here forces a relaunch before the automation phase. With
    # credentials that is harmless — we log back in. On a session the customer
    # handed us interactively it is not: the replayed cookie snapshot may no
    # longer be accepted, and the window visibly disappears mid-run. Keep the
    # browser we already have.
    if not has_session():
        quit_driver()

    print("  ALM + XPEDITE EXPORT")
    print("-" * 68)
    # Exports are a side deliverable — never let one fail a customer's test run.
    # alm_out/xpedite_out are referenced unconditionally further down, so a
    # skipped export must still leave them defined.
    alm_out = None
    xpedite_out = None
    try:
        alm_out = export_discovery_to_alm(discovery, scenarios_filter=selected)
        print(f"  ALM:     {alm_out}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ALM export skipped: {exc}")
    try:
        xpedite_out = export_discovery_to_xpedite(discovery, password)
        print(f"  Xpedite: {xpedite_out}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Xpedite export skipped: {exc}")
    page_html = REPORTS_DIR / "latest-page-map.html"

    # ---- Automation runs ONLY when user explicitly enables it ----
    if not run_tests:
        total_ms = (time.perf_counter() - started) * 1000
        print()
        print("=" * 68)
        print("  COMPLETE — TEST CASES CREATED (automation NOT run)")
        print(f"  Module(s):  {', '.join(selected)}")
        print(f"  Test cases: {len(auto)}")
        print(f"  ALM:        {alm_out}")
        print(f"  Xpedite:    {xpedite_out}")
        if page_html.is_file():
            print(f"  Page map:   {page_html}")
        print()
        print("  Automation chalane ke liye:")
        print('    app-input.json me  "run_automation": true  karo')
        print("    phir SAME RUN.bat dubara chalao")
        print("=" * 68)
        if open_outputs and xpedite_out is not None:
            webbrowser.open(xpedite_out.resolve().as_uri())
        return 0

    print()
    print("  AUTOMATION RUN (run_automation: true)")
    print("-" * 68)
    start_browser(url)
    logger = ExecutionLogger("module-tc-run")
    if on_step_progress:
        logger.on_progress = on_step_progress
    results = run_all_automation(
        discovery,
        password,
        logger,
        logout_after_each=logout_after_each,
        continue_on_failure=True,
        role_hint=role_hint,
        run_modules_only=selected,
        run_test_cases_only=selected_test_case_ids,
    )
    for r in results:
        mark = "PASS" if r.status == "PASS" else "FAIL"
        print(f"  {r.tc_id}: {mark} — {r.title}")

    try:
        alm_out = export_discovery_to_alm(
            discovery,
            scenarios_filter=selected,
            execution_results=results,
        )
        print(f"  ALM (with results): {alm_out}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ALM export skipped: {exc}")

    total_ms = (time.perf_counter() - started) * 1000
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    report_path = write_html_report(
        automation_results=results,
        manual_scenarios=[],
        execution_log=logger.content,
        suite_name=f"{', '.join(selected)} — {app_name}",
        environment=url,
        total_duration_ms=total_ms,
        show_execution_log=inp.get("show_execution_log_in_report", False),
    )
    latest = REPORTS_DIR / "latest-e2e-report.html"

    print()
    print("=" * 68)
    print("  COMPLETE — TEST CASES + AUTOMATION RUN")
    print(f"  Module(s): {', '.join(selected)}")
    print(f"  ALM:       {alm_out}")
    print(f"  Xpedite:   {xpedite_out}")
    print(f"  Report:    {report_path}")
    if page_html.is_file():
        print(f"  Page map:  {page_html}")
    print(f"  Result:    {passed}/{len(results)} passed")
    print("=" * 68)

    if open_outputs:
        if xpedite_out is not None:
            webbrowser.open(xpedite_out.resolve().as_uri())
        webbrowser.open(latest.resolve().as_uri())
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="UTS two-cycle automation")
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Cycle 1 only: login + scan all modules (ignore module in config)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run automation after creating test cases (same as run_automation: true)",
    )
    args, _unknown = parser.parse_known_args()

    inp = load_input()
    url = inp["url"].strip()
    app_name = inp.get("app_name") or url.split("//")[-1].split("/")[0]
    wanted = [] if args.scan_only else get_module_names_from_input(inp)

    print()
    print("=" * 68)
    print("  UTS AUTOMATION")
    print(f"  App: {app_name}")
    print(f"  URL: {url}")
    if wanted:
        print(f"  app-input module(s): {', '.join(wanted)}")
    else:
        print("  app-input module: (blank)")
    print("=" * 68)
    print()

    try:
        # ---- CYCLE 1: module blank → SCAN MODULES ONLY → stop ----
        if not wanted:
            print("[CYCLE 1] First run — SCAN MODULES only (no test cases)")
            print()
            scan_modules_to_json(inp)
            print("=" * 68)
            print("  CYCLE 1 COMPLETE")
            print("  Output: generated\\modules.json")
            print()
            print("  NEXT (Cycle 2):")
            print("    1. Open config\\app-input.json")
            print('    2. Set  "module": "Admin"   (or Admin#PIM)')
            print("    3. Run SAME RUN.bat again")
            print("       -> creates test cases for selected module + runs them")
            print("=" * 68)
            return 0

        # ---- CYCLE 2: module set → CREATE TCs for selected module + run ----
        print("[CYCLE 2] Second run — CREATE TEST CASES for selected module")
        print()

        if not modules_catalog_exists():
            print("  modules.json missing — running Cycle 1 scan first...")
            print()
            catalog = scan_modules_to_json(inp)
        else:
            catalog = load_modules_catalog()
            print(f"  modules.json loaded ({len(catalog)} modules from Cycle 1)")

        found, missing = match_modules(wanted, catalog)

        if missing:
            for m in missing:
                print(f"  !! '{m}' modules.json me NAHI mila")
        if not found:
            print()
            print("  Available modules (from Cycle 1 scan):")
            print_module_menu(catalog)
            print("  app-input.json me sahi naam daal kar dubara chalao.")
            return 1

        # Automation runs ONLY if user explicitly enables it
        run_tests = bool(inp.get("run_automation", False)) or args.run

        print(f"  Selected module(s) verified: {', '.join(found)}")
        if run_tests:
            print("  run_automation: TRUE — TCs banenge + automation chalega")
        else:
            print("  run_automation: FALSE — sirf TCs banenge (automation nahi chalega)")
        print()
        return create_and_run(inp, found, run_tests=run_tests)

    finally:
        shutdown_all()


if __name__ == "__main__":
    raise SystemExit(main())
