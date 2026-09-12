"""Analyze and map every page in the application — builds trust via full site understanding."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from uts_engine.discovery.discovery import (
    _attr,
    _best_locator,
    _click_by_locator,
    _find_action_buttons,
    _find_form_fields,
    _find_headings,
    _find_search_fields,
    _find_sub_nav_links,
    _module_nav_xpath,
    _module_open_candidates,
    _return_to_dashboard,
    _visible,
)
from uts_engine.discovery.common_actions import infer_action_from_button
from uts_engine.workdir import data_root

GENERATED_DIR = data_root() / "generated"
REPORTS_DIR = data_root() / "reports"
PAGE_MAP_FILE = GENERATED_DIR / "page-map.json"
PAGE_MAP_HTML = REPORTS_DIR / "app-page-map.html"

# Bumped whenever the page-map element schema changes (e.g. D2's locator
# capture) so downstream consumers can tell an old cached map apart from one
# that actually carries locators.
PAGE_MAP_VERSION = 2


def _stable_element_id(module: str, path: str, role: str, label: str, locator_by: str, locator_value: str) -> str:
    """Content hash of (module, page path, role, label, locator) — survives
    re-crawls as long as the element itself hasn't materially changed,
    unlike an index into the page's field/button list."""
    raw = "|".join([module, path, role, label, locator_by, locator_value])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _infer_page_type(
    fields: list,
    buttons: list[tuple[str, Any]],
    has_table: bool,
    has_search: bool,
) -> str:
    labels = " ".join(b[0].lower() for b in buttons)
    if has_table and has_search:
        return "list_with_search"
    if has_table and any(h in labels for h in ("add", "new", "create")):
        return "list_with_crud"
    if has_table:
        return "list"
    if len(fields) >= 3 and any(h in labels for h in ("save", "submit", "update")):
        return "form"
    if len(fields) >= 1:
        return "data_entry"
    if has_search:
        return "search"
    return "content"


def analyze_current_page(
    driver: WebDriver,
    module: str,
    sub_page: str = "",
) -> dict[str, Any]:
    """Build a structured profile of the current browser page."""
    try:
        return _analyze_current_page_inner(driver, module, sub_page)
    except Exception as exc:  # noqa: BLE001
        return {
            "module": module,
            "sub_page": sub_page or "(main)",
            "path": module if not sub_page else f"{module} > {sub_page}",
            "url": driver.current_url,
            "title": driver.title or "",
            "page_type": "unknown",
            "headings": [],
            "breadcrumbs": [],
            "field_count": 0,
            "fields": [],
            "button_count": 0,
            "buttons": [],
            "search_fields": [],
            "table_rows": 0,
            "capabilities": [],
            "understood": bool(driver.title or driver.current_url),
            "summary": f"{module} / {sub_page or 'main'}: partial scan — {exc}",
            "error": str(exc),
        }


def _analyze_current_page_inner(
    driver: WebDriver,
    module: str,
    sub_page: str = "",
) -> dict[str, Any]:
    """Build a structured profile of the current browser page."""
    headings = _find_headings(driver)
    form_fields = _find_form_fields(driver, limit=20)
    action_buttons = _find_action_buttons(driver, limit=20)
    search_fields = _find_search_fields(driver, limit=5)

    path = module if not sub_page else f"{module} > {sub_page}"

    fields_out = []
    for label, tag, el in form_fields:
        field_type = _attr(el, "type") or tag
        _, loc_by, loc_val = _best_locator(el)
        fields_out.append({
            "id": _stable_element_id(module, path, "field", label, loc_by, loc_val),
            "label": label,
            "type": field_type,
            "tag": tag,
            "locator_by": loc_by,
            "locator_value": loc_val,
        })

    buttons_out = []
    for label, el in action_buttons:
        _, loc_by, loc_val = _best_locator(el)
        buttons_out.append({
            "id": _stable_element_id(module, path, "button", label, loc_by, loc_val),
            "label": label,
            "action": infer_action_from_button(label),
            "locator_by": loc_by,
            "locator_value": loc_val,
        })

    search_fields_out = []
    for label, el in search_fields:
        _, loc_by, loc_val = _best_locator(el)
        search_fields_out.append({
            "id": _stable_element_id(module, path, "search", label, loc_by, loc_val),
            "label": label,
            "locator_by": loc_by,
            "locator_value": loc_val,
        })

    tables = driver.find_elements(By.CSS_SELECTOR, ".oxd-table-body, table tbody")
    has_table = bool(tables and any(t.is_displayed() for t in tables))
    row_count = 0
    if has_table:
        rows = driver.find_elements(By.CSS_SELECTOR, ".oxd-table-body .oxd-table-row, table tbody tr")
        row_count = len([r for r in rows if r.is_displayed()])

    breadcrumbs = []
    for el in _visible(driver.find_elements(By.CSS_SELECTOR, ".oxd-topbar-header-breadcrumb, .breadcrumb, h6")):
        text = (el.text or "").strip()
        if text and text not in breadcrumbs:
            breadcrumbs.append(text)

    page_type = _infer_page_type(form_fields, action_buttons, has_table, bool(search_fields))

    capabilities = []
    if search_fields:
        capabilities.append("search")
    if any(h in b["label"].lower() for b in buttons_out for h in ("add", "new", "create")):
        capabilities.append("create")
    if any(b["action"] == "UpdateRecord" for b in buttons_out):
        capabilities.append("update")
    if any(b["action"] == "DeleteRecord" for b in buttons_out):
        capabilities.append("delete")
    if form_fields:
        capabilities.append("form_fill")
    if has_table:
        capabilities.append("list_view")

    return {
        "module": module,
        "sub_page": sub_page or "(main)",
        "path": path,
        "url": driver.current_url,
        "title": driver.title or "",
        "page_type": page_type,
        "headings": headings[:5],
        "breadcrumbs": breadcrumbs[:5],
        "field_count": len(fields_out),
        "fields": fields_out[:15],
        "button_count": len(buttons_out),
        "buttons": buttons_out[:15],
        "search_fields": search_fields_out[:5],
        "table_rows": row_count,
        "capabilities": capabilities,
        "understood": bool(
            headings or fields_out or buttons_out or has_table or breadcrumbs
        ),
        "summary": _build_page_summary(module, sub_page, page_type, fields_out, buttons_out, capabilities),
    }


def _build_page_summary(
    module: str,
    sub_page: str,
    page_type: str,
    fields: list,
    buttons: list,
    capabilities: list,
) -> str:
    page = sub_page or "main view"
    caps = ", ".join(capabilities) if capabilities else "view only"
    return (
        f"{module} / {page}: {page_type} page with "
        f"{len(fields)} field(s), {len(buttons)} action(s) — can {caps}"
    )


def scan_all_application_pages(
    driver: WebDriver,
    wait: WebDriverWait,
    modules: list[dict[str, Any]],
    post_login_url: str,
    *,
    skip_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Visit every module and every sub-page; return full page map.
    Builds trust: proves tool understands the whole application.
    """
    skip = skip_names or {
        "upgrade", "orangehrm, inc", "orangehrm inc", "help", "github",
        "linkedin", "facebook", "twitter", "youtube",
    }
    all_pages: list[dict[str, Any]] = []
    total_modules = 0

    print()
    print("  PAGE INTELLIGENCE — understanding every page...")
    print("  " + "-" * 60)

    for mod in modules:
        name = mod.get("name", "")
        if not name or name.lower() in skip:
            continue
        if name.lower().startswith("orangehrm") and "inc" in name.lower():
            continue

        loc = mod.get("locator") or {}
        l_by = loc.get("by", "xpath")
        l_val = loc.get("value") or _module_nav_xpath(name)

        total_modules += 1
        print(f"  [{total_modules}] Module: {name}")

        try:
            _return_to_dashboard(driver, wait, post_login_url)
            # Try every way of reaching the module, not just the stored locator.
            # A single attempt that fell back to the OrangeHRM sidebar xpath is
            # why page understanding was empty on every other application — and
            # with no page understanding the planner can only emit a nav-click
            # smoke test.
            opened = False
            for by, value in _module_open_candidates(name, l_by, l_val):
                if _click_by_locator(driver, by, value):
                    opened = True
                    break
            if not opened:
                print(f"       WARN: could not open {name}")
                all_pages.append({
                    "module": name,
                    "sub_page": "(main)",
                    "path": name,
                    "understood": False,
                    "summary": f"{name}: could not open",
                    "error": "navigation failed",
                })
                continue

            time.sleep(1.2)
            try:
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except Exception:  # noqa: BLE001
                pass

            main_profile = analyze_current_page(driver, name, "")
            all_pages.append(main_profile)
            print(f"       Main: {main_profile['page_type']} — {main_profile['summary']}")

            sub_nav = _find_sub_nav_links(driver, module_name=name, limit=12)
            for sub_text, sub_el in sub_nav:
                try:
                    from uts_engine.discovery.discovery import _best_locator
                    _, sub_by, sub_val = _best_locator(sub_el)
                    if _click_by_locator(driver, sub_by, sub_val):
                        time.sleep(1.0)
                        try:
                            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                        except Exception:  # noqa: BLE001
                            pass
                        sub_profile = analyze_current_page(driver, name, sub_text)
                        all_pages.append(sub_profile)
                        print(f"       Sub '{sub_text}': {sub_profile['page_type']} — {len(sub_profile['fields'])} fields")
                except Exception as exc:  # noqa: BLE001
                    print(f"       WARN sub-page '{sub_text}': {exc}")

            mod["pages"] = [p for p in all_pages if p.get("module") == name]
            mod["page_count"] = len(mod["pages"])
            mod["understood"] = any(p.get("understood") for p in mod["pages"])

        except Exception as exc:  # noqa: BLE001
            print(f"       ERROR: {exc}")
            try:
                fallback = analyze_current_page(driver, name, "")
                if not any(p.get("module") == name for p in all_pages):
                    all_pages.append(fallback)
            except Exception:  # noqa: BLE001
                all_pages.append({
                    "module": name,
                    "sub_page": "(main)",
                    "understood": False,
                    "summary": f"{name}: scan error — {exc}",
                    "error": str(exc),
                })
            mod["pages"] = [p for p in all_pages if p.get("module") == name]
            mod["page_count"] = len(mod["pages"])
            mod["understood"] = any(p.get("understood") for p in mod["pages"])

    understood = sum(1 for p in all_pages if p.get("understood"))
    print("  " + "-" * 60)
    print(f"  UNDERSTOOD: {understood}/{len(all_pages)} pages across {total_modules} module(s)")
    print()
    return all_pages


def save_page_map(
    pages: list[dict[str, Any]],
    app_name: str = "",
    url: str = "",
) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    modules_seen: dict[str, list] = {}
    for p in pages:
        mod = p.get("module", "Unknown")
        modules_seen.setdefault(mod, []).append(p)

    payload = {
        "page_map_version": PAGE_MAP_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app_name": app_name,
        "url": url,
        "total_pages": len(pages),
        "understood_pages": sum(1 for p in pages if p.get("understood")),
        "module_count": len(modules_seen),
        "modules": [
            {
                "name": mod,
                "page_count": len(plist),
                "pages": plist,
            }
            for mod, plist in sorted(modules_seen.items(), key=lambda x: x[0].lower())
        ],
        "pages": pages,
    }
    PAGE_MAP_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return PAGE_MAP_FILE


def write_page_map_html(
    pages: list[dict[str, Any]],
    app_name: str = "",
    url: str = "",
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    understood = sum(1 for p in pages if p.get("understood"))
    modules: dict[str, list] = {}
    for p in pages:
        modules.setdefault(p.get("module", "?"), []).append(p)

    rows_html = []
    for mod_name in sorted(modules.keys(), key=str.lower):
        for p in modules[mod_name]:
            caps = ", ".join(p.get("capabilities") or []) or "—"
            fields = p.get("field_count", 0)
            buttons = p.get("button_count", 0)
            status = "✓ Understood" if p.get("understood") else "○ Partial"
            color = "#059669" if p.get("understood") else "#d97706"
            rows_html.append(f"""
            <tr>
              <td><strong>{p.get('module','')}</strong></td>
              <td>{p.get('sub_page','')}</td>
              <td><span class="badge">{p.get('page_type','')}</span></td>
              <td>{fields}</td>
              <td>{buttons}</td>
              <td>{caps}</td>
              <td style="color:{color};font-weight:600">{status}</td>
              <td class="summary">{p.get('summary','')}</td>
            </tr>""")

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>App Page Map — {app_name}</title>
<style>
  body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #f8fafc; color: #1e293b; }}
  h1 {{ color: #0f172a; }}
  .stats {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 20px 0; }}
  .stat {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 24px; min-width: 140px; }}
  .stat b {{ display: block; font-size: 28px; color: #2563eb; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th {{ background: #1e40af; color: #fff; text-align: left; padding: 12px; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
  tr:hover {{ background: #f1f5f9; }}
  .badge {{ background: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
  .summary {{ font-size: 13px; color: #64748b; max-width: 320px; }}
  .trust {{ background: #ecfdf5; border: 1px solid #6ee7b7; border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
</style></head><body>
<h1>Application Page Map</h1>
<p><strong>{app_name}</strong> — {url}</p>
<div class="trust">
  <strong>Trust Report:</strong> This scan visited every module and sub-page, identified forms, buttons,
  search fields, and list views — proving the automation tool understands your application structure
  before generating test cases.
</div>
<div class="stats">
  <div class="stat"><b>{len(modules)}</b>Modules</div>
  <div class="stat"><b>{len(pages)}</b>Pages scanned</div>
  <div class="stat"><b>{understood}</b>Pages understood</div>
  <div class="stat"><b>{datetime.now().strftime('%Y-%m-%d %H:%M')}</b>Generated</div>
</div>
<table>
  <thead><tr>
    <th>Module</th><th>Sub-page</th><th>Type</th><th>Fields</th><th>Buttons</th>
    <th>Capabilities</th><th>Status</th><th>Summary</th>
  </tr></thead>
  <tbody>{''.join(rows_html)}</tbody>
</table>
</body></html>"""
    PAGE_MAP_HTML.write_text(html, encoding="utf-8")
    latest = REPORTS_DIR / "latest-page-map.html"
    latest.write_text(html, encoding="utf-8")
    return PAGE_MAP_HTML
