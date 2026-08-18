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
from workdir import data_root

ROOT = Path(__file__).resolve().parent.parent
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
        steps.append(
            {
                "step_no": 2,
                "action": "Verify",
                "object_name": "Home",
                "input_value": _observed_marker(discovery) or url,
                "locator_by": "",
                "locator_value": "",
                "expected": "Application opened",
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
    steps.append(
        {
            "step_no": n,
            "action": "Verify",
            "object_name": "PostLogin",
            "input_value": _observed_marker(discovery) or "Dashboard",
            "locator_by": "",
            "locator_value": "",
            "expected": "Logged in successfully" if (has_creds or has_form) else "Application opened",
            "concept": "verification",
        }
    )
    return steps


def _observed_marker(discovery: dict) -> str:
    """Something the crawl actually saw, for home / post-login verification.

    Never ``app_name``: that is the label the customer typed into our form. Almost
    no application prints it back, so asserting on it manufactures failures — it
    is what turned a run whose every real step passed into a FAIL.
    """
    title = str(discovery.get("page_title") or "").strip()
    if title:
        return title
    from urllib.parse import urlsplit

    target = str(discovery.get("post_login_url") or discovery.get("url") or "")
    return urlsplit(target).netloc


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
    nav_steps.append(
        {
            "step_no": n,
            "action": "Verify",
            "object_name": f"{module} Page",
            "input_value": module,
            "locator_by": "",
            "locator_value": "",
            "expected": f"{module} page visible",
            "concept": "verification",
        }
    )
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
    if fields or "form_fill" in caps or "create" in caps:
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
        add_btn = next(
            (b for b in buttons if any(h in (b.get("label") or "").lower() for h in ("add", "new", "create"))),
            None,
        )
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

        save_btn = next(
            (b for b in buttons if any(h in (b.get("label") or "").lower() for h in ("save", "submit", "apply"))),
            None,
        )
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
        if cfg.get("include_verification", True):
            fill_steps.append(
                {
                    "step_no": n,
                    "action": "Notification",
                    "object_name": "Success",
                    "input_value": "success",
                    "locator_by": "css",
                    "locator_value": ".oxd-toast, [role='alert'], .toast",
                    "expected": "Record saved",
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
    if cfg.get("include_negative", True) and fields:
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
        add_btn = next(
            (b for b in buttons if any(h in (b.get("label") or "").lower() for h in ("add", "new", "create"))),
            None,
        )
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
        save_btn = next(
            (b for b in buttons if any(h in (b.get("label") or "").lower() for h in ("save", "submit"))),
            {"label": "Save"},
        )
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
        neg_steps.append(
            {
                "step_no": n,
                "action": "Verify",
                "object_name": "Validation",
                "input_value": "Required",
                "locator_by": "",
                "locator_value": "",
                "expected": "Validation error shown for empty required fields",
                "concept": "verification",
            }
        )
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

    # 4) Search if available
    if "search" in caps or page.get("search_fields"):
        search_label = (page.get("search_fields") or ["Search"])[0]
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
                {
                    "step_no": n + 2,
                    "action": "PerformClick",
                    "object_name": "Search",
                    "input_value": "",
                    "locator_by": "xpath",
                    "locator_value": "//button[contains(normalize-space(.),'Search')]",
                    "expected": "",
                    "concept": "click",
                },
                {
                    "step_no": n + 3,
                    "action": "Verify",
                    "object_name": "Results",
                    "input_value": module,
                    "locator_by": "",
                    "locator_value": "",
                    "expected": "Search results displayed",
                    "concept": "verification",
                },
            ]
        )
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

    for mod in modules:
        page = page_by_module.get(mod) or {
            "module": mod,
            "fields": [],
            "buttons": [{"label": "Add", "action": "UpdateRecord"}, {"label": "Save", "action": "UpdateRecord"}],
            "capabilities": ["create", "form_fill", "search", "list_view"],
            "search_fields": ["Search"],
            "path": mod,
        }
        scenarios.extend(_module_flow_scenarios(mod, page, discovery, username, cfg))

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
