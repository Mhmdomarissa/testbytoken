"""
Export discovered scenarios to Xpedite format only (no Selenium run).
Uses templates from templates/xpedite/ (same as Converter Dynamic).
"""

from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dynamic.discovery import DiscoveryResult, ScenarioDef, StepDef
from xpedite.exporter import export_discovery_to_xpedite

GENERATED = ROOT / "generated" / "discovered-flow.json"
INPUT_FILE = ROOT / "config" / "app-input.json"


def load_discovery_from_file() -> tuple[DiscoveryResult, str]:
    if not GENERATED.exists():
        raise FileNotFoundError("Run run_dynamic.py first to discover UI, or provide discovered-flow.json")

    data = json.loads(GENERATED.read_text(encoding="utf-8"))
    scenarios = []
    for s in data["scenarios"]:
        steps = [StepDef(**st) for st in s["steps"]]
        scenarios.append(ScenarioDef(s["id"], s["type"], s["title"], steps))

    discovery = DiscoveryResult(
        url=data["url"],
        username=data["username"],
        app_name=data["app_name"],
        page_title=data["page_title"],
        discovered_at=data["discovered_at"],
        login_url=data["login_url"],
        post_login_url=data["post_login_url"],
        scenarios=scenarios,
        locators=data.get("locators", {}),
    )

    password = "Pass@123"
    if INPUT_FILE.exists():
        password = json.loads(INPUT_FILE.read_text(encoding="utf-8-sig")).get("password", password)

    return discovery, password


def main() -> int:
    print()
    print("=" * 64)
    print("  UTS -> XPEDITE EXPORT")
    print("  Output format: Converter Dynamic templates")
    print("=" * 64)
    print()

    discovery, password = load_discovery_from_file()
    discovery.scenarios = [s for s in discovery.scenarios if s.type == "automation"]
    out = export_discovery_to_xpedite(discovery, password)

    print(f"Generated Xpedite test cases in:\n  {out}\n")
    print("Files:")
    print("  TestData.xlsx")
    print("  TC_*.xml / BPW_*.xml / BC_*.xml")
    print()

    try:
        import os
        os.startfile(str(out))  # noqa: S606
    except Exception:
        webbrowser.open(out.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
