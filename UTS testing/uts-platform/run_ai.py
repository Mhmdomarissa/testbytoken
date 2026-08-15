"""
UTS AI mode — give URL (+ login) and AI understands the app, then builds:
  link, object repository, enter/sendKeys, verification, data-driven, BDD
and optionally runs automation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from run_automation_only import (  # noqa: E402
    create_and_run,
    get_module_names_from_input,
    load_input,
    match_modules,
    scan_modules_to_json,
)
from dynamic.module_selector import (  # noqa: E402
    load_modules_catalog,
    modules_catalog_exists,
    print_module_menu,
)
from automation.selenium_session import shutdown_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="UTS AI: URL → understand → objects/BDD/data-driven/verification → run"
    )
    parser.add_argument("--url", default="", help="Override application URL")
    parser.add_argument("--username", default="", help="Override username")
    parser.add_argument("--password", default="", help="Override password")
    parser.add_argument("--modules", default="", help="Module(s), e.g. Admin or Admin#PIM")
    parser.add_argument("--all-modules", action="store_true", help="After scan, use all modules")
    parser.add_argument("--run", action="store_true", help="Also execute Selenium automation")
    parser.add_argument("--scan-only", action="store_true", help="Only scan modules")
    args = parser.parse_args()

    inp = load_input()
    if args.url:
        inp["url"] = args.url
    if args.username:
        inp["username"] = args.username
    if args.password:
        inp["password"] = args.password
    if args.modules:
        inp["module"] = args.modules

    inp["ai_mode"] = True
    if args.run:
        inp["run_automation"] = True

    print()
    print("=" * 68)
    print("  UTS AI AUTOMATION")
    print("  Give URL → AI understands → link / object / enter / verify /")
    print("  data-driven / BDD → optional run")
    print(f"  URL: {inp.get('url')}")
    print("=" * 68)
    print()

    try:
        if args.scan_only:
            scan_modules_to_json(inp)
            return 0

        wanted = get_module_names_from_input(inp)
        if not wanted and not args.all_modules:
            print("[AI] No module set — scanning all modules first...")
            catalog = scan_modules_to_json(inp)
            print()
            print("  Next: set module in config/app-input.json, or re-run with:")
            print('    python run_ai.py --modules Admin --run')
            print("    python run_ai.py --all-modules --run")
            print_module_menu(catalog)
            return 0

        if not modules_catalog_exists():
            print("[AI] modules.json missing — scanning first...")
            catalog = scan_modules_to_json(inp)
        else:
            catalog = load_modules_catalog()

        if args.all_modules or not wanted:
            wanted = [m["name"] for m in catalog if m.get("name")]

        found, missing = match_modules(wanted, catalog)
        if missing:
            for m in missing:
                print(f"  !! module not found: {m}")
        if not found:
            print_module_menu(catalog)
            return 1

        return create_and_run(
            inp,
            found,
            run_tests=bool(inp.get("run_automation")),
            open_outputs=True,
        )
    finally:
        shutdown_all()


if __name__ == "__main__":
    raise SystemExit(main())
