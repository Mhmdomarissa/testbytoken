"""
AI brain: understand an application from URL + page map, then plan automation
covering link, object, enter/sendKeys, verification, data-driven, and BDD.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uts_engine.workdir import data_root

# services/engine/, two levels above this file (uts_engine/planning/).
ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config" / "ai.json"
GENERATED_DIR = data_root() / "generated"


def load_ai_config() -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "enabled": True,
        "provider": "offline",
        "model": "gpt-4o-mini",
        "api_key_env": "UTS_AI_API_KEY",
        "base_url": "",
        "temperature": 0.2,
        "max_tokens": 4000,
        "generate_bdd": True,
        "generate_object_repo": True,
        "generate_data_driven": True,
        "data_driven_rows": 3,
        "include_negative": True,
        "include_verification": True,
        "concepts": [
            "link",
            "object",
            "verification",
            "enter",
            "send_keys",
            "data_driven",
            "bdd",
            "click",
            "select",
            "notification",
        ],
    }
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            cfg.update({k: v for k, v in raw.items() if not str(k).startswith("_")})
        except Exception:  # noqa: BLE001
            pass

    # Env overrides
    provider = (os.getenv("UTS_AI_PROVIDER") or "").strip()
    if provider:
        cfg["provider"] = provider
    model = (os.getenv("UTS_AI_MODEL") or "").strip()
    if model:
        cfg["model"] = model
    base = (os.getenv("UTS_AI_BASE_URL") or "").strip()
    if base:
        cfg["base_url"] = base
    key_env = cfg.get("api_key_env") or "UTS_AI_API_KEY"
    api_key = (os.getenv(key_env) or os.getenv("OPENAI_API_KEY") or "").strip()
    cfg["api_key"] = api_key
    if cfg.get("provider") in {"openai", "azure_openai", "gemini", "claude"} and not api_key:
        cfg["provider"] = "offline"
    return cfg


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip()).strip("_")
    return s[:48] or "Item"


def _sample_value(label: str, field_type: str, row: int = 1) -> str:
    low = f"{label} {field_type}".lower()
    if any(h in low for h in ("pass", "pwd")):
        return f"Pass@{row}23"
    if any(h in low for h in ("email", "mail")):
        return f"user{row}@example.com"
    if any(h in low for h in ("phone", "mobile", "tel")):
        return f"98765432{row:02d}"
    if any(h in low for h in ("date", "dob")):
        return f"2026-0{(row % 9) + 1}-15"
    if any(h in low for h in ("number", "qty", "amount", "age", "count")):
        return str(10 * row)
    if field_type in {"checkbox", "radio"}:
        return "true"
    return f"Auto{label.replace(' ', '')[:12]}{row}"


def build_object_repository(
    discovery: dict[str, Any],
    page_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Object repository from locators + page fields (AI concept: Object)."""
    objects: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name, loc in (discovery.get("locators") or {}).items():
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        objects.append(
            {
                "name": name,
                "concept": "object",
                "locator_by": loc.get("by") or loc.get("locator_by") or "",
                "locator_value": loc.get("value") or loc.get("locator_value") or "",
                "page": "shared",
                "module": "",
                "stable_score": 80 if (loc.get("by") or "").lower() in {"id", "name"} else 55,
            }
        )

    for page in (page_map or {}).get("pages") or []:
        module = page.get("module") or ""
        path = page.get("path") or module
        for field in page.get("fields") or []:
            label = field.get("label") or "field"
            key = f"{module}:{label}".lower()
            if key in seen:
                continue
            seen.add(key)
            objects.append(
                {
                    "name": label,
                    "concept": "object",
                    "locator_by": "xpath",
                    "locator_value": (
                        f"//*[self::input or self::textarea or self::select]"
                        f"[contains(@placeholder,'{label}') or contains(@name,'{label}') "
                        f"or @id='{label}']"
                    ),
                    "page": path,
                    "module": module,
                    "field_type": field.get("type") or field.get("tag") or "text",
                    "stable_score": 50,
                }
            )
        for btn in page.get("buttons") or []:
            label = btn.get("label") or "button"
            key = f"{module}:btn:{label}".lower()
            if key in seen:
                continue
            seen.add(key)
            objects.append(
                {
                    "name": label,
                    "concept": "object",
                    "locator_by": "xpath",
                    "locator_value": f"//button[contains(normalize-space(.),'{label}')] | //a[contains(normalize-space(.),'{label}')]",
                    "page": path,
                    "module": module,
                    "action_hint": btn.get("action") or "PerformClick",
                    "stable_score": 50,
                }
            )
    return objects


def _has_login_surface(discovery: dict[str, Any], username: str = "", password: str = "") -> bool:
    """True when the app looks like it has a login form or project credentials exist."""
    locators = discovery.get("locators") or {}
    if locators.get("username") or locators.get("user") or locators.get("password"):
        return True
    if locators.get("login_button") or locators.get("submit"):
        return True
    if (username or "").strip() or (password or "").strip():
        return True
    return False


def _login_steps(
    discovery: dict[str, Any],
    username: str,
    password: str = "",
) -> list[dict]:
    """
    Build open-app / login steps.

    Public sites (no login locators and no project credentials) get Navigate + Verify only.
    Do NOT invent Password/Login clicks when the page has no login form.
    """
    locators = discovery.get("locators") or {}
    url = discovery.get("login_url") or discovery.get("url") or ""
    steps: list[dict] = [
        {
            "step_no": 1,
            "action": "Navigate",
            "object_name": "Application URL",
            "input_value": url,
            "locator_by": "",
            "locator_value": "",
            "expected": "Application page",
            "concept": "link",
        }
    ]

    user_loc = locators.get("username") or locators.get("user") or {}
    pass_loc = locators.get("password") or {}
    login_loc = locators.get("login_button") or locators.get("submit") or {}
    has_creds = bool((username or "").strip()) or bool((password or "").strip())
    has_form = bool(user_loc or pass_loc or login_loc)

    if not has_form and not has_creds:
        # No form to log into — the only thing the crawl observed to check is
        # that we actually landed on the target URL rather than an error page
        # or a redirect elsewhere.
        if url:
            steps.append(
                {
                    "step_no": 2,
                    "action": "Verify",
                    "object_name": "Home",
                    "input_value": "",
                    "locator_by": "",
                    "locator_value": "",
                    "expected": url,
                    "assertion": "url_matches",
                    "concept": "verification",
                }
            )
        return steps

    n = 2
    if user_loc or (username or "").strip():
        steps.append(
            {
                "step_no": n,
                "action": "SetText",
                "object_name": "Username",
                "input_value": username or "{{Username}}",
                "locator_by": user_loc.get("by", ""),
                "locator_value": user_loc.get("value", ""),
                "expected": "",
                "concept": "enter",
            }
        )
        n += 1
    if pass_loc or (password or "").strip():
        steps.append(
            {
                "step_no": n,
                "action": "SetPassword",
                "object_name": "Password",
                "input_value": password if (password or "").strip() else "********",
                "locator_by": pass_loc.get("by", ""),
                "locator_value": pass_loc.get("value", ""),
                "expected": "",
                "concept": "send_keys",
            }
        )
        n += 1
    if login_loc or user_loc or pass_loc or has_creds:
        steps.append(
            {
                "step_no": n,
                "action": "PerformClick",
                "object_name": "Login",
                "input_value": "",
                "locator_by": login_loc.get("by", ""),
                "locator_value": login_loc.get("value", ""),
                "expected": "Dashboard",
                "concept": "click",
            }
        )
        n += 1
    post_login_step = _post_login_verify_step(discovery, url, step_no=n)
    if post_login_step is not None:
        steps.append(post_login_step)
    return steps


def _post_login_verify_step(discovery: dict[str, Any], login_url: str, step_no: int) -> dict[str, Any] | None:
    """Build a post-login Verify only from what the crawl actually observed.

    Preferred: element_visible on the first observed module's own nav locator
    — that element only exists in the authenticated shell. Fallback:
    url_matches, but only if the URL genuinely changed after login (an SPA
    that never changes URL gives us nothing honest to check there). If
    neither is available, emit no step — a navigation-only scenario is more
    honest than an invented expectation.
    """
    modules = discovery.get("modules") or []
    first = next((m for m in modules if isinstance(m, dict) and m.get("locator")), None)
    if first is not None:
        loc = first["locator"] or {}
        if loc.get("by") and loc.get("value"):
            return {
                "step_no": step_no,
                "action": "Verify",
                "object_name": "PostLogin",
                "input_value": "",
                "locator_by": loc["by"],
                "locator_value": loc["value"],
                "expected": first.get("name", ""),
                "assertion": "element_visible",
                "concept": "verification",
            }

    post_login_url = str(discovery.get("post_login_url") or "")
    if post_login_url and post_login_url != login_url:
        return {
            "step_no": step_no,
            "action": "Verify",
            "object_name": "PostLogin",
            "input_value": "",
            "locator_by": "",
            "locator_value": "",
            "expected": post_login_url,
            "assertion": "url_matches",
            "concept": "verification",
        }
    return None


def _module_link_xpath(module: str) -> str:
    """Flexible link locator — exact text match is too brittle on marketing sites."""
    safe = (module or "").replace("'", "")
    return (
        f"//a[contains(normalize-space(.),'{safe}')] "
        f"| //button[contains(normalize-space(.),'{safe}')] "
        f"| //*[@role='link' or self::span or self::div]"
        f"[contains(normalize-space(.),'{safe}')]/ancestor::a[1]"
    )


def _module_flow_scenarios(
    module: str,
    page: dict[str, Any],
    discovery: dict[str, Any],
    username: str,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Heuristic AI planner covering all automation concepts for one module."""
    scenarios: list[dict[str, Any]] = []
    fields = page.get("fields") or []
    buttons = page.get("buttons") or []
    caps = set(page.get("capabilities") or [])
    slug = _slug(module)
    login = _login_steps(discovery, username, str(discovery.get('password') or ''))

    # Resolved once, from buttons the crawl actually saw. Everything below asks
    # these rather than assuming a page has Add/Save — a filter dropdown is not
    # a data-entry form, and asserting on controls that are not there produces
    # failures about our guesses instead of about the application.
    def _button(*hints: str) -> dict[str, Any] | None:
        return next(
            (b for b in buttons if any(h in (b.get("label") or "").lower() for h in hints)),
            None,
        )

    add_btn = _button("add", "new", "create")
    save_btn = _button("save", "submit", "apply")

    # 1) Link / navigation smoke
    nav_steps = [dict(s) for s in login]
    n = len(nav_steps) + 1
    nav_steps.append(
        {
            "step_no": n,
            "action": "PerformClick",
            "object_name": module,
            "input_value": "",
            "locator_by": "xpath",
            "locator_value": _module_link_xpath(module),
            "expected": module,
            "concept": "link",
        }
    )
    n += 1
    page_url = str(page.get("url") or "")
    if page_url:
        # url_matches on the URL the crawl actually recorded for this page —
        # not an invented "page visible" expectation.
        nav_steps.append(
            {
                "step_no": n,
                "action": "Verify",
                "object_name": f"{module} Page",
                "input_value": "",
                "locator_by": "",
                "locator_value": "",
                "expected": page_url,
                "assertion": "url_matches",
                "concept": "verification",
            }
        )
        n += 1
    scenarios.append(
        {
            "id": f"TC_AI_LINK_{slug}",
            "type": "automation",
            "title": f"[AI] Navigate link to {module}",
            "module": module,
            "concepts": ["link", "object", "verification", "bdd"],
            "bdd": {
                "feature": f"{module} Navigation",
                "scenario": f"User opens {module} module via menu link",
                "given": "Application is open",
                "when": f"User clicks the {module} link",
                "then": f"{module} page is displayed",
            },
            "steps": nav_steps,
        }
    )

    # 2) Enter / sendKeys / object fill + verify
    # Only worth a data-entry test if the page offers a way to submit one.
    if (save_btn or add_btn) and (fields or "form_fill" in caps or "create" in caps):
        fill_steps = [dict(s) for s in login]
        n = len(fill_steps) + 1
        fill_steps.append(
            {
                "step_no": n,
                "action": "PerformClick",
                "object_name": module,
                "input_value": "",
                "locator_by": "xpath",
                "locator_value": _module_link_xpath(module),
                "expected": module,
                "concept": "link",
            }
        )
        n += 1
        if add_btn:
            fill_steps.append(
                {
                    "step_no": n,
                    "action": "PerformClick",
                    "object_name": add_btn.get("label") or "Add",
                    "input_value": "",
                    "locator_by": "xpath",
                    "locator_value": f"//button[contains(normalize-space(.),'{add_btn.get('label')}')]",
                    "expected": "",
                    "concept": "click",
                }
            )
            n += 1

        data_row: dict[str, str] = {}
        for field in fields[:8]:
            label = field.get("label") or "Field"
            ftype = field.get("type") or field.get("tag") or "text"
            value = _sample_value(label, ftype, 1)
            data_row[label] = value
            action = "SetPassword" if "pass" in label.lower() else "SetText"
            if ftype in {"select", "select-one"}:
                action = "PerformSelect"
            fill_steps.append(
                {
                    "step_no": n,
                    "action": action,
                    "object_name": label,
                    "input_value": f"{{{{{label}}}}}" if cfg.get("generate_data_driven") else value,
                    "locator_by": "xpath",
                    "locator_value": (
                        f"//*[self::input or self::textarea or self::select]"
                        f"[contains(@placeholder,'{label}') or contains(@name,'{label}')]"
                    ),
                    "expected": "",
                    "concept": "send_keys" if action != "PerformSelect" else "select",
                }
            )
            n += 1

        if save_btn:
            fill_steps.append(
                {
                    "step_no": n,
                    "action": "PerformClick",
                    "object_name": save_btn.get("label") or "Save",
                    "input_value": "",
                    "locator_by": "xpath",
                    "locator_value": f"//button[contains(normalize-space(.),'{save_btn.get('label')}')]",
                    "expected": "",
                    "concept": "click",
                }
            )
            n += 1
        # A success toast only means something if we actually submitted.
        if save_btn and cfg.get("include_verification", True):
            # No locator here on purpose — no single CSS class for a toast is
            # true across apps. The runner falls back to the generic
            # [role='alert'] ARIA pattern when a step carries none.
            fill_steps.append(
                {
                    "step_no": n,
                    "action": "Notification",
                    "object_name": "Success",
                    "input_value": "",
                    "locator_by": "",
                    "locator_value": "",
                    "expected": "success",
                    "concept": "verification",
                }
            )

        scenario: dict[str, Any] = {
            "id": f"TC_AI_ENTER_{slug}",
            "type": "automation",
            "title": f"[AI] Enter / sendKeys / save on {module}",
            "module": module,
            "concepts": ["object", "enter", "send_keys", "verification", "bdd", "data_driven"],
            "bdd": {
                "feature": f"{module} Data Entry",
                "scenario": f"User fills form fields on {module} and saves",
                "given": "User is on the form page",
                "when": "User enters valid data and clicks Save",
                "then": "Success notification is shown",
            },
            "steps": fill_steps,
        }
        if cfg.get("generate_data_driven") and data_row:
            rows = [dict(data_row)]
            for i in range(2, int(cfg.get("data_driven_rows") or 3) + 1):
                rows.append({k: _sample_value(k, "text", i) for k in data_row})
            scenario["data_driven"] = True
            scenario["data_rows"] = rows
            scenario["data_sheet"] = f"AI_{slug}"
        scenarios.append(scenario)

    # 3) Negative verification
    # Submitting an empty form to check validation needs a real submit button.
    if cfg.get("include_negative", True) and fields and save_btn:
        neg_steps = [dict(s) for s in login]
        n = len(neg_steps) + 1
        neg_steps.append(
            {
                "step_no": n,
                "action": "PerformClick",
                "object_name": module,
                "input_value": "",
                "locator_by": "xpath",
                "locator_value": _module_link_xpath(module),
                "expected": module,
                "concept": "link",
            }
        )
        n += 1
        if add_btn:
            neg_steps.append(
                {
                    "step_no": n,
                    "action": "PerformClick",
                    "object_name": add_btn.get("label") or "Add",
                    "input_value": "",
                    "locator_by": "xpath",
                    "locator_value": f"//button[contains(normalize-space(.),'{add_btn.get('label')}')]",
                    "expected": "",
                    "concept": "click",
                }
            )
            n += 1
        neg_steps.append(
            {
                "step_no": n,
                "action": "PerformClick",
                "object_name": save_btn.get("label") or "Save",
                "input_value": "",
                "locator_by": "xpath",
                "locator_value": f"//button[contains(normalize-space(.),'{save_btn.get('label') or 'Save'}')]",
                "expected": "",
                "concept": "click",
            }
        )
        n += 1
        # No Verify here on purpose: the crawl does not observe a validation-
        # message locator, so there is nothing checkable to assert on yet
        # (would need the page-map locator capture from W5). This scenario
        # stays a click-only smoke test — it proves empty-submit doesn't
        # crash the app, and no more, until that locator exists.
        scenarios.append(
            {
                "id": f"TC_AI_NEG_{slug}",
                "type": "negative",
                "title": f"[AI] Negative validation on {module}",
                "module": module,
                "concepts": ["verification", "object", "bdd"],
                "bdd": {
                    "feature": f"{module} Validation",
                    "scenario": f"User submits empty {module} form",
                    "given": "User opened the create form",
                    "when": "User clicks Save without entering data",
                    "then": "Required field validation messages appear",
                },
                "steps": neg_steps,
            }
        )

    # 4) Search — only when the crawl actually found a search box.
    if page.get("search_fields"):
        search_label = page["search_fields"][0]
        search_btn = _button("search", "find", "filter", "apply", "go")
        search_steps = [dict(s) for s in login]
        n = len(search_steps) + 1
        search_steps.extend(
            [
                {
                    "step_no": n,
                    "action": "PerformClick",
                    "object_name": module,
                    "input_value": "",
                    "locator_by": "xpath",
                    "locator_value": _module_link_xpath(module),
                    "expected": module,
                    "concept": "link",
                },
                {
                    "step_no": n + 1,
                    "action": "SetText",
                    "object_name": search_label,
                    "input_value": "{{SearchTerm}}",
                    "locator_by": "xpath",
                    "locator_value": f"//input[contains(@placeholder,'{search_label}') or contains(@name,'search')]",
                    "expected": "",
                    "concept": "enter",
                },
            ]
        )
        n += 2
        # Plenty of search boxes filter as you type and have no button at all.
        # Only click one we actually saw.
        if search_btn:
            label = search_btn.get("label") or "Search"
            search_steps.append(
                {
                    "step_no": n,
                    "action": "PerformClick",
                    "object_name": label,
                    "input_value": "",
                    "locator_by": "xpath",
                    "locator_value": f"//button[contains(normalize-space(.),'{label}')]",
                    "expected": "",
                    "concept": "click",
                }
            )
            n += 1
        # No Verify here on purpose: page_map's table_rows is a crawl-time
        # count, not a re-queryable locator (row_count needs the step's own
        # locator_by/locator_value — that capture is W5). This scenario stays
        # search-only until then, rather than asserting on the module name
        # appearing anywhere on the page (the exact vacuous-pass bug this
        # phase exists to fix).
        scenarios.append(
            {
                "id": f"TC_AI_SEARCH_{slug}",
                "type": "automation",
                "title": f"[AI] Search / filter on {module}",
                "module": module,
                "concepts": ["enter", "object", "verification", "data_driven", "bdd"],
                "bdd": {
                    "feature": f"{module} Search",
                    "scenario": f"User searches records on {module}",
                    "given": f"User is on {module} list",
                    "when": "User enters a search term and clicks Search",
                    "then": "Matching results are shown",
                },
                "data_driven": True,
                "data_sheet": f"AI_Search_{slug}",
                "data_rows": [
                    {"SearchTerm": "Admin"},
                    {"SearchTerm": "Test"},
                    {"SearchTerm": "Auto"},
                ],
                "steps": search_steps,
            }
        )

    return scenarios


def offline_understand(
    discovery: dict[str, Any],
    page_map: dict[str, Any] | None,
    modules: list[str],
    username: str,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Rule-based AI planner (works without API key)."""
    pages = (page_map or {}).get("pages") or []
    page_by_module: dict[str, dict] = {}
    for p in pages:
        mod = p.get("module") or ""
        if mod and mod not in page_by_module:
            page_by_module[mod] = p
        # Prefer main page over sub-pages
        if mod and (p.get("sub_page") in {"", "(main)", None}):
            page_by_module[mod] = p

    if not modules:
        modules = list(page_by_module.keys()) or [m.get("name") for m in (discovery.get("modules") or []) if m.get("name")]

    scenarios: list[dict[str, Any]] = []
    password = str(discovery.get("password") or "")
    # Only emit login TC when the app has a login form or project credentials.
    # Public marketing sites (e.g. pmi.org) must not get fake Password/Login steps.
    if _has_login_surface(discovery, username, password):
        scenarios.append(
            {
                "id": "TC_AI_LOGIN",
                "type": "automation",
                "title": "[AI] Login with enter / sendKeys / verify",
                "module": "",
                "concepts": ["enter", "send_keys", "object", "verification", "bdd"],
                "bdd": {
                    "feature": "Authentication",
                    "scenario": "Valid user logs in",
                    "given": "Login page is open",
                    "when": "User enters username and password and clicks Login",
                    "then": "Dashboard is displayed",
                },
                "steps": _login_steps(discovery, username, password),
            }
        )
    else:
        scenarios.append(
            {
                "id": "TC_AI_OPEN_APP",
                "type": "automation",
                "title": "[AI] Open application URL and verify",
                "module": "",
                "concepts": ["link", "verification", "bdd"],
                "bdd": {
                    "feature": "Application Launch",
                    "scenario": "User opens the application",
                    "given": "Browser is available",
                    "when": "User navigates to the application URL",
                    "then": "Home page is displayed",
                },
                "steps": _login_steps(discovery, username, password),
            }
        )

    unread: list[str] = []
    for mod in modules:
        page = page_by_module.get(mod)
        if not page or not page.get("understood"):
            # No readable profile for this module. Previously we substituted an
            # invented one — Add/Save buttons and a Search box that were never
            # on the page — which generated tests guaranteed to fail on elements
            # that do not exist. Generate only what we can stand behind.
            unread.append(mod)
            page = {
                "module": mod,
                "fields": [],
                "buttons": [],
                "capabilities": [],
                "search_fields": [],
                "path": mod,
            }
        scenarios.extend(_module_flow_scenarios(mod, page, discovery, username, cfg))

    if unread:
        print(
            "  NOTE: no page detail for "
            + ", ".join(unread)
            + " — navigation tests only. Open the module with 'Look inside' to "
            "see whether the crawl can reach it."
        )

    objects = build_object_repository(discovery, page_map) if cfg.get("generate_object_repo", True) else []
    return {
        "provider": "offline",
        "understood": True,
        "summary": (
            f"Understood {len(modules)} module(s); planned {len(scenarios)} AI scenarios "
            f"covering link, object, enter, sendKeys, verification, data-driven, BDD."
        ),
        "concepts_covered": cfg.get("concepts") or [],
        "modules": modules,
        "objects": objects,
        "scenarios": scenarios,
    }


def _chat_completions(cfg: dict[str, Any], system: str, user: str) -> str:
    provider = (cfg.get("provider") or "offline").lower()
    api_key = cfg.get("api_key") or ""
    model = cfg.get("model") or "gpt-4o-mini"
    temperature = float(cfg.get("temperature") or 0.2)
    max_tokens = int(cfg.get("max_tokens") or 4000)

    if provider == "ollama":
        base = (cfg.get("base_url") or "http://127.0.0.1:11434/v1").rstrip("/")
        url = f"{base}/chat/completions"
        headers = {"Content-Type": "application/json"}
        body = {
            "model": model or "llama3.2",
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    elif provider == "azure_openai":
        base = (cfg.get("base_url") or "").rstrip("/")
        if not base or not api_key:
            raise RuntimeError("Azure OpenAI requires base_url and api key")
        url = f"{base}/openai/deployments/{model}/chat/completions?api-version=2024-10-21"
        headers = {"Content-Type": "application/json", "api-key": api_key}
        body = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    elif provider == "openai":
        base = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        body = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    else:
        raise RuntimeError(f"Unsupported live provider: {provider}")

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
        raise


def llm_understand(
    discovery: dict[str, Any],
    page_map: dict[str, Any] | None,
    modules: list[str],
    username: str,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Ask an LLM to plan automation using all concepts; fall back to offline on error."""
    compact_pages = []
    for p in (page_map or {}).get("pages") or []:
        if modules and p.get("module") not in modules:
            continue
        compact_pages.append(
            {
                "module": p.get("module"),
                "path": p.get("path"),
                "page_type": p.get("page_type"),
                "fields": [f.get("label") for f in (p.get("fields") or [])][:10],
                "buttons": [b.get("label") for b in (p.get("buttons") or [])][:10],
                "capabilities": p.get("capabilities") or [],
            }
        )

    system = (
        "You are a senior test automation architect. "
        "Given a web app URL discovery and page map, produce JSON test scenarios "
        "that cover: link/navigation, object repository names, enter/sendKeys, "
        "click, select, verification, notification, data-driven rows, and BDD "
        "(Given/When/Then). Use only these step actions: Navigate, SetText, "
        "SetPassword, PerformClick, PerformSelect, Verify, Notification. "
        "Return strict JSON with keys: summary, scenarios (array). "
        "Each scenario: id, type (automation|negative), title, module, concepts, "
        "bdd {feature,scenario,given,when,then}, steps [{step_no,action,object_name,"
        "input_value,locator_by,locator_value,expected,concept}], optional data_rows."
    )
    user = json.dumps(
        {
            "url": discovery.get("url"),
            "app_name": discovery.get("app_name"),
            "username": username,
            "modules": modules,
            "pages": compact_pages,
            "locator_keys": list((discovery.get("locators") or {}).keys())[:40],
        },
        ensure_ascii=False,
    )

    try:
        raw = _chat_completions(cfg, system, user)
        parsed = _extract_json(raw)
        scenarios = parsed.get("scenarios") or []
        # Ensure login steps exist and renumber
        for sc in scenarios:
            steps = sc.get("steps") or []
            for i, st in enumerate(steps, start=1):
                st["step_no"] = i
            sc.setdefault("type", "automation")
            sc.setdefault("concepts", cfg.get("concepts") or [])
        objects = build_object_repository(discovery, page_map)
        return {
            "provider": cfg.get("provider"),
            "understood": True,
            "summary": parsed.get("summary")
            or f"LLM planned {len(scenarios)} scenario(s) for {', '.join(modules)}",
            "concepts_covered": cfg.get("concepts") or [],
            "modules": modules,
            "objects": objects,
            "scenarios": scenarios,
        }
    except Exception as exc:  # noqa: BLE001
        fallback = offline_understand(discovery, page_map, modules, username, cfg)
        fallback["summary"] = f"LLM unavailable ({exc}); used offline AI planner. " + fallback["summary"]
        fallback["provider"] = f"{cfg.get('provider')}->offline"
        return fallback


def understand_application(
    discovery: dict[str, Any],
    page_map: dict[str, Any] | None = None,
    modules: list[str] | None = None,
    username: str = "",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Main entry: URL discovery + page map → AI automation plan."""
    cfg = cfg or load_ai_config()
    modules = modules or []
    provider = (cfg.get("provider") or "offline").lower()
    if not cfg.get("enabled", True):
        return offline_understand(discovery, page_map, modules, username, cfg)
    if provider == "offline":
        return offline_understand(discovery, page_map, modules, username, cfg)
    return llm_understand(discovery, page_map, modules, username, cfg)
