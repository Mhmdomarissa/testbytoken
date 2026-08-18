"""Module catalog + interactive selection for discover-once / rerun-selected."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from dynamic.module_filter import parse_module_from_description, slugify_module as slugify
from dynamic.discovery import DiscoveryResult, ScenarioDef
from workdir import data_root

GENERATED_DIR = data_root() / "generated"
MODULES_FILE = GENERATED_DIR / "modules.json"
FLOW_FILE = GENERATED_DIR / "discovered-flow.json"


def slugify(name: str) -> str:
    return slugify_module(name)


def build_modules_catalog(discovery: DiscoveryResult) -> list[dict[str, Any]]:
    """Build module list from tagged scenarios (and fallback from titles)."""
    buckets: dict[str, dict[str, Any]] = {}

    for s in discovery.scenarios:
        if s.type != "automation":
            continue
        module = (getattr(s, "module", "") or "").strip()
        if not module:
            # Fallback: "Admin: Users — app" or "Explore Admin — app"
            title = s.title or ""
            if ":" in title:
                module = title.split(":", 1)[0].strip()
            elif title.lower().startswith("explore "):
                module = title[8:].split("—")[0].split("-")[0].strip()
            else:
                continue
        if module.lower() in ("login", "post-login", "core"):
            continue
        key = slugify(module)
        if key not in buckets:
            buckets[key] = {
                "id": key,
                "name": module,
                "scenario_ids": [],
            }
        if s.id not in buckets[key]["scenario_ids"]:
            buckets[key]["scenario_ids"].append(s.id)

    # Prefer modules list already on discovery if present
    if getattr(discovery, "modules", None):
        for m in discovery.modules:
            mid = m.get("id") or slugify(m.get("name", ""))
            if mid not in buckets:
                buckets[mid] = {
                    "id": mid,
                    "name": m.get("name") or mid,
                    "scenario_ids": list(m.get("scenario_ids") or []),
                }
            else:
                for sid in m.get("scenario_ids") or []:
                    if sid not in buckets[mid]["scenario_ids"]:
                        buckets[mid]["scenario_ids"].append(sid)

    return sorted(buckets.values(), key=lambda x: x["name"].lower())


def save_modules_catalog(modules: list[dict[str, Any]], app_name: str = "", url: str = "") -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "app_name": app_name,
        "url": url,
        "module_count": len(modules),
        "modules": modules,
    }
    MODULES_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return MODULES_FILE


def load_modules_catalog() -> list[dict[str, Any]]:
    if not MODULES_FILE.exists():
        return []
    data = json.loads(MODULES_FILE.read_text(encoding="utf-8-sig"))
    return list(data.get("modules") or [])


def modules_catalog_exists() -> bool:
    return MODULES_FILE.exists()


def discovery_exists() -> bool:
    return FLOW_FILE.exists()


def filter_discovery_by_modules(
    discovery: DiscoveryResult,
    selected: list[str],
    include_login: bool = True,
) -> DiscoveryResult:
    """
    Keep only scenarios for selected module names/ids.
    Always optionally keeps TC_AUTO_01 (login) so session can start cleanly.
    Empty selected → keep everything (ALL modules).
    """
    if not selected:
        return discovery

    selected_norm = {slugify(x) for x in selected}
    selected_raw = {x.strip().lower() for x in selected}

    def scenario_matches(s: ScenarioDef) -> bool:
        if include_login and s.id == "TC_AUTO_01":
            return True
        if include_login and (getattr(s, "module", "") or "").lower() in ("login", "core"):
            return True
        mod = (getattr(s, "module", "") or "").strip()
        if mod and (slugify(mod) in selected_norm or mod.lower() in selected_raw):
            return True
        title_l = (s.title or "").lower()
        for sel in selected:
            if sel.lower() in title_l:
                return True
        return False

    catalog = load_modules_catalog()
    allowed_ids = set()
    for m in catalog:
        if slugify(m["id"]) in selected_norm or m["name"].lower() in selected_raw:
            allowed_ids.update(m.get("scenario_ids") or [])

    filtered = []
    for s in discovery.scenarios:
        if s.id in allowed_ids or scenario_matches(s):
            filtered.append(s)

    seen = set()
    unique = []
    for s in filtered:
        if s.id in seen:
            continue
        seen.add(s.id)
        unique.append(s)

    discovery.scenarios = unique
    return discovery


def print_module_menu(modules: list[dict[str, Any]]) -> None:
    print()
    print("  Website modules:")
    print("  " + "-" * 50)
    if not modules:
        print("  (none yet — pehle option 1 se list karo)")
        return
    for i, m in enumerate(modules, 1):
        n = len(m.get("scenario_ids") or [])
        extra = f"  ({n} TC)" if n else ""
        print(f"  {i:2d}. {m['name']}{extra}")
    print("  " + "-" * 50)


def prompt_main_menu(has_modules: bool) -> str:
    """
    Returns one of: list | generate | export | quit
    """
    print()
    print("=" * 68)
    print("  UTS — 2 STEP FLOW")
    print("=" * 68)
    print("  1) LIST modules from website")
    if has_modules:
        print("  2) GENERATE test cases for selected modules")
        print("     (blank selection = ALL modules)")
        print("  3) Re-export Xpedite only")
    else:
        print("  2) (locked) Generate — pehle modules list karo (option 1)")
        print("  3) (locked) Export — pehle list karo")
    print("  0) Quit")
    print("=" * 68)

    while True:
        choice = input("  Enter choice [1]: ").strip() or "1"
        if choice == "0":
            return "quit"
        if choice == "1":
            return "list"
        if choice == "2" and has_modules:
            return "generate"
        if choice == "3" and has_modules:
            return "export"
        print("  Invalid choice. Try again.")


def prompt_module_selection(modules: list[dict[str, Any]]) -> list[str] | None:
    """
    Interactive multi-select.
    Returns:
      - list of names when user picks modules
      - empty list [] when user wants ALL (Enter / all / blank)
      - None only if modules list is empty
    """
    if not modules:
        return None

    print_module_menu(modules)
    print("  Select module number(s) or name(s).")
    print("  Blank / Enter / 'all'  =>  generate for ALL modules")
    print("  Examples:  1   |  1,3   |  Admin   |  Admin,PIM")
    raw = input("  Select [ALL]: ").strip()
    if not raw or raw.lower() == "all":
        print("  => ALL modules")
        return []  # empty = all

    parts = [p.strip() for p in re.split(r"[,;]+", raw) if p.strip()]
    selected: list[str] = []
    for p in parts:
        if p.isdigit():
            idx = int(p)
            if 1 <= idx <= len(modules):
                selected.append(modules[idx - 1]["name"])
            else:
                print(f"  !! Skipping invalid number: {p}")
        else:
            hit = None
            for m in modules:
                if m["name"].lower() == p.lower() or m["id"] == slugify(p):
                    hit = m["name"]
                    break
            if not hit:
                for m in modules:
                    if p.lower() in m["name"].lower():
                        hit = m["name"]
                        break
            if hit:
                selected.append(hit)
            else:
                print(f"  !! Module not found: {p}")

    out = []
    seen = set()
    for s in selected:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    if not out:
        print("  => No valid pick — generating for ALL modules")
        return []
    print(f"  => Selected: {', '.join(out)}")
    return out


def resolve_selected_from_input(inp: dict, modules: list[dict[str, Any]]) -> list[str]:
    """
    From app-input.json:
      "selected_modules": ["Admin", "PIM"]  → those modules
      "selected_modules": [] or missing      → ALL (return [])
    """
    raw = inp.get("selected_modules")
    if isinstance(raw, list) and raw:
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [p.strip() for p in re.split(r"[,;]+", raw) if p.strip()]

    from dynamic.module_filter import parse_module_from_description

    mod = parse_module_from_description(inp.get("description") or "")
    if mod and modules:
        for m in modules:
            if slugify(m["name"]) == slugify(mod) or mod.lower() in m["name"].lower():
                return [m["name"]]
        return [mod]
    return []  # nothing given → ALL
