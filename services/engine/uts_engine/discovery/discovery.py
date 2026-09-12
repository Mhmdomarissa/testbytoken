"""Discover UI elements from any URL using Selenium."""

from __future__ import annotations

import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from uts_engine.discovery.login_helpers import (
    fill_username_and_trigger_role,
    find_role_select,
    perform_language_selection,
    perform_role_selection,
)
from uts_engine.discovery.common_actions import infer_action_from_button
from uts_engine.discovery.module_filter import matches_module, parse_module_from_description, slugify_module

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


@dataclass
class StepDef:
    step_no: int
    action: str
    object_name: str
    input_value: str = ""
    locator_by: str = ""
    locator_value: str = ""
    expected: str = ""
    # Closed assertion vocabulary for `verify` steps (E3): url_matches,
    # element_visible, text_in_region, row_count. `expected` carries the
    # argument; empty/unknown here means the step is never checkable and
    # a verify always FAILs rather than assuming a soft pass.
    assertion: str = ""


@dataclass
class ScenarioDef:
    id: str
    type: str  # manual | automation
    title: str
    steps: list[StepDef] = field(default_factory=list)
    module: str = ""  # e.g. Admin, PIM — empty for core/login


@dataclass
class DiscoveryResult:
    url: str
    username: str
    app_name: str
    page_title: str
    discovered_at: str
    login_url: str
    post_login_url: str
    scenarios: list[ScenarioDef] = field(default_factory=list)
    locators: dict[str, dict[str, str]] = field(default_factory=dict)
    modules: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "username": self.username,
            "app_name": self.app_name,
            "page_title": self.page_title,
            "discovered_at": self.discovered_at,
            "login_url": self.login_url,
            "post_login_url": self.post_login_url,
            "locators": self.locators,
            "modules": self.modules,
            "pages": self.pages,
            "scenarios": [
                {
                    "id": s.id,
                    "type": s.type,
                    "title": s.title,
                    "module": s.module,
                    "steps": [asdict(st) for st in s.steps],
                }
                for s in self.scenarios
            ],
        }


USER_HINTS = ("user", "email", "login", "uid", "account", "name")
SUBMIT_HINTS = ("login", "sign in", "signin", "submit", "log in", "continue")
ADD_HINTS = ("add", "new", "create", "insert", "+")
SAVE_HINTS = ("save", "submit", "update", "confirm", "apply", "send", "store")
SEARCH_HINTS = ("search", "find", "filter", "go", "query")
SKIP_FIELD_HINTS = ("username", "password", "txtuser", "txtpass", "dllrole", "role")
DELETE_HINTS = ("delete", "remove", "cancel")
CANCEL_HINTS = ("cancel", "close", "back")

AUTOMATION_TYPES = frozenset({"automation", "positive", "negative"})


def _first_line(text: str) -> str:
    """Safe first line — avoids IndexError on empty button/label text."""
    lines = (text or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _visible(elements: list[WebElement]) -> list[WebElement]:
    return [el for el in elements if el.is_displayed()]


def _attr(el: WebElement, name: str) -> str:
    return (el.get_attribute(name) or "").strip()


def _label_for(el: WebElement) -> str:
    el_id = _attr(el, "id")
    if el_id:
        try:
            labels = el.parent.find_elements(By.CSS_SELECTOR, f"label[for='{el_id}']")
            if labels and labels[0].text.strip():
                return labels[0].text.strip()
        except Exception:  # noqa: BLE001
            pass
    placeholder = _attr(el, "placeholder")
    if placeholder:
        return placeholder
    name = _attr(el, "name")
    if name:
        return name
    return el_id or "field"


def _best_locator(el: WebElement) -> tuple[str, str, str]:
    el_id = _attr(el, "id")
    if el_id:
        return f"el_{el_id}", "id", el_id
    name = _attr(el, "name")
    if name:
        return f"el_{name}", "name", name
    tag = el.tag_name.lower()
    text = (el.text or "").strip()[:40]
    if text:
        safe = re.sub(r"[^a-zA-Z0-9]", "_", text)[:30]
        return f"el_{safe}", "xpath", f"//{tag}[normalize-space()='{text}']"
    css = tag
    for attr in ("type", "class"):
        val = _attr(el, attr)
        if val:
            css += f"[{attr}='{val}']"
            break
    return f"el_{tag}", "css", css


def _score_username(el: WebElement) -> int:
    text = " ".join(
        [
            _attr(el, "id"),
            _attr(el, "name"),
            _attr(el, "placeholder"),
            _attr(el, "type"),
            _label_for(el),
        ]
    ).lower()
    score = 0
    if _attr(el, "type") in ("text", "email", ""):
        score += 2
    for hint in USER_HINTS:
        if hint in text:
            score += 3
    if "pass" in text:
        score -= 5
    return score


def _find_username(driver: WebDriver) -> WebElement | None:
    candidates = _visible(
        driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='email'], input:not([type])")
    )
    candidates = [c for c in candidates if _attr(c, "type") not in ("password", "hidden", "submit", "button")]
    if not candidates:
        return None
    return max(candidates, key=_score_username)


def _find_password(driver: WebDriver) -> WebElement | None:
    fields = _visible(driver.find_elements(By.CSS_SELECTOR, "input[type='password']"))
    return fields[0] if fields else None


def _find_submit(driver: WebDriver) -> WebElement | None:
    buttons = _visible(
        driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit'], a.btn, [role='button']")
    )
    scored: list[tuple[int, WebElement]] = []
    for btn in buttons:
        label = " ".join([btn.text, _attr(btn, "value"), _attr(btn, "id"), _attr(btn, "name")]).lower()
        score = 0
        for hint in SUBMIT_HINTS:
            if hint in label:
                score += 5
        if btn.tag_name == "button" and _attr(btn, "type") == "submit":
            score += 3
        if score > 0:
            scored.append((score, btn))
    if scored:
        return max(scored, key=lambda x: x[0])[1]
    submits = _visible(driver.find_elements(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']"))
    if submits:
        return submits[0]
    visible_buttons = _visible(driver.find_elements(By.TAG_NAME, "button"))
    return visible_buttons[0] if visible_buttons else None


def _find_headings(driver: WebDriver) -> list[str]:
    titles = []
    for tag in ("h1", "h2", "title"):
        if tag == "title":
            t = driver.title
            if t:
                titles.append(t.strip())
        else:
            for el in _visible(driver.find_elements(By.TAG_NAME, tag))[:3]:
                text = el.text.strip()
                if text and text not in titles:
                    titles.append(text)
    return titles


def _find_nav_links(driver: WebDriver, limit: int = 25) -> list[tuple[str, WebElement]]:
    """Collect visible nav/menu items (modules). Higher limit for first-run full scan."""
    links = []
    seen = set()
    skip = {
        "", "login", "logout", "sign out", "signout", "help", "search",
        "skip to main content", "skip to content",
        "upgrade", "orangehrm, inc", "orangehrm inc",
    }
    selectors = (
        "nav a, aside a, .oxd-main-menu a, .sidebar a, "
        "[role='menuitem'], [role='navigation'] a, "
        "a, button, [role='link']"
    )
    for el in _visible(driver.find_elements(By.CSS_SELECTOR, selectors)):
        text = _first_line(el.text or _attr(el, "value") or _attr(el, "aria-label") or "")
        if not text or len(text) > 60:
            continue
        key = text.lower()
        if key in seen or key in skip:
            continue
        seen.add(key)
        links.append((text, el))
        if len(links) >= limit:
            break
    return links


def _find_form_fields(driver: WebDriver, limit: int = 12) -> list[tuple[str, str, WebElement]]:
    fields = []
    seen_keys: set[str] = set()
    selectors = (
        "input, select, textarea, "
        ".oxd-input input, .oxd-textbox input, .oxd-input-group input"
    )
    for el in _visible(driver.find_elements(By.CSS_SELECTOR, selectors)):
        typ = _attr(el, "type").lower()
        tag = el.tag_name.lower()
        if typ in ("hidden", "submit", "button", "file"):
            continue
        if typ == "password":
            continue
        if _attr(el, "readonly") or _attr(el, "disabled"):
            continue
        el_id = _attr(el, "id").lower()
        el_name = _attr(el, "name").lower()
        if any(h in el_id or h in el_name for h in SKIP_FIELD_HINTS):
            continue
        label = _label_for(el)
        dedupe = f"{label.lower()}|{el_name}|{el_id}"
        if dedupe in seen_keys:
            continue
        seen_keys.add(dedupe)
        fields.append((label, tag, el))
        if len(fields) >= limit:
            break
    return fields


def _find_search_fields(driver: WebDriver, limit: int = 3) -> list[tuple[str, WebElement]]:
    """Search/filter inputs on list pages."""
    fields: list[tuple[str, WebElement]] = []
    seen: set[str] = set()

    area_selectors = (
        ".oxd-table-filter input, .oxd-table-filter-area input, "
        "[class*='table-filter'] input, .oxd-form-row input"
    )
    candidates: list[WebElement] = []
    for sel in area_selectors.split(", "):
        candidates.extend(driver.find_elements(By.CSS_SELECTOR, sel))
    candidates.extend(
        driver.find_elements(
            By.CSS_SELECTOR,
            "input[type='text'], input[type='search'], input:not([type]), .oxd-input input",
        )
    )

    for el in _visible(candidates):
        if _attr(el, "readonly") or _attr(el, "disabled"):
            continue
        label = _label_for(el).lower()
        placeholder = _attr(el, "placeholder").lower()
        combined = f"{label} {placeholder} {_attr(el, 'name').lower()} {_attr(el, 'id').lower()}"
        is_search = any(
            h in combined
            for h in SEARCH_HINTS + ("hint", "employee", "username", "user", "name", "type for")
        )
        in_filter = bool(
            el.find_elements(By.XPATH, "./ancestor::*[contains(@class,'table-filter')]")
        )
        if not is_search and not in_filter:
            continue
        key = _attr(el, "name") or _attr(el, "id") or label
        if key in seen:
            continue
        seen.add(key)
        fields.append((_label_for(el) or "Search", el))
        if len(fields) >= limit:
            break
    return fields


def _find_action_buttons(driver: WebDriver, limit: int = 15) -> list[tuple[str, WebElement]]:
    """Find visible action buttons: Add, Save, Search, Update, etc."""
    buttons = []
    seen = set()
    selectors = (
        "button, input[type='submit'], input[type='button'], "
        "a.btn, [role='button'], .oxd-button, [class*='oxd-button']"
    )
    for el in _visible(driver.find_elements(By.CSS_SELECTOR, selectors)):
        label = _first_line(
            el.text or _attr(el, "value") or _attr(el, "aria-label") or _attr(el, "title") or ""
        )
        if not label or len(label) > 40:
            continue
        key = label.lower()
        if key in seen:
            continue
        if not any(
            hint in key
            for hints in (ADD_HINTS, SAVE_HINTS, SEARCH_HINTS, DELETE_HINTS)
            for hint in hints
        ):
            continue
        seen.add(key)
        buttons.append((label, el))
        if len(buttons) >= limit:
            break
    return buttons


def _get_select_options(el: WebElement) -> list[str]:
    try:
        options = Select(el).options
        values = []
        for opt in options:
            text = (opt.text or "").strip()
            val = (opt.get_attribute("value") or "").strip()
            if text and text.lower() not in ("-- select --", "select", ""):
                values.append(text)
            elif val and val not in ("", "0"):
                values.append(val)
        return values[:5]
    except Exception:  # noqa: BLE001
        return []


def _sample_value_for_field(label: str, tag: str, el: WebElement, index: int) -> str:
    typ = _attr(el, "type").lower()
    label_lower = label.lower()
    if typ == "email" or "email" in label_lower:
        return f"autotest{index}@example.com"
    if typ == "number" or any(h in label_lower for h in ("amount", "qty", "quantity", "count")):
        return str(100 + index)
    if typ == "tel" or "phone" in label_lower:
        return "9876543210"
    if "date" in label_lower:
        return "2026-07-20"
    if any(h in label_lower for h in ("name", "title", "subject")):
        return f"AutoTest{index}"
    if "description" in label_lower or tag == "textarea":
        return f"Automated test entry {index + 1}"
    return f"test_{index + 1}"


def _return_to_dashboard(driver: WebDriver, wait: WebDriverWait, post_login_url: str) -> None:
    try:
        from uts_engine.automation.selenium_session import navigate

        navigate(driver, post_login_url)
        wait.until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
        time.sleep(1)
    except Exception:  # noqa: BLE001
        time.sleep(1)


def _click_by_locator(driver: WebDriver, by: str, value: str) -> bool:
    by_map = {
        "id": By.ID,
        "name": By.NAME,
        "css": By.CSS_SELECTOR,
        "xpath": By.XPATH,
        "class": By.CLASS_NAME,
    }
    try:
        el = driver.find_element(by_map.get(by, By.ID), value)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.3)
        try:
            el.click()
        except Exception:  # noqa: BLE001
            driver.execute_script("arguments[0].click();", el)
        return True
    except Exception:  # noqa: BLE001
        return False


def _sidebar_module_names(driver: WebDriver) -> set[str]:
    names: set[str] = set()
    for el in driver.find_elements(By.CSS_SELECTOR, ".oxd-main-menu-item, aside a, nav.oxd-navbar-nav a"):
        text = _first_line(el.text or _attr(el, "aria-label") or "").lower()
        if text:
            names.add(text)
    return names


def _module_nav_xpath(link_text: str) -> str:
    """OrangeHRM's sidebar. Kept as one candidate among many — never as the only one."""
    safe = link_text.replace("'", "''")
    return (
        f"//nav[contains(@class,'oxd-navbar-nav')]"
        f"//a[normalize-space()='{safe}']"
    )


def _module_open_candidates(
    link_text: str, l_by: str, l_val: str
) -> list[tuple[str, str]]:
    """Ways to open a module, best first.

    The locator the scan actually captured leads, because it was observed working
    on this application. Generic text matches come next, and the OrangeHRM
    sidebar xpath is last — it only matches one product, and preferring it over a
    known-good locator is how module exploration silently fails everywhere else.
    """
    safe = link_text.replace("'", "''")
    candidates: list[tuple[str, str]] = []
    if l_by and l_val:
        candidates.append((l_by, l_val))
    candidates += [
        ("xpath", f"//a[normalize-space()='{safe}']"),
        ("xpath", f"//*[self::a or self::button or @role='button'][normalize-space()='{safe}']"),
        ("xpath", f"//a[contains(normalize-space(),'{safe}')]"),
        ("xpath", _module_nav_xpath(link_text)),
    ]
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    for pair in candidates:
        if pair not in seen:
            seen.add(pair)
            ordered.append(pair)
    return ordered


def _find_sub_nav_links(driver: WebDriver, module_name: str = "", limit: int = 12) -> list[tuple[str, WebElement]]:
    """Tabs/sub-pages inside an opened module header — never main sidebar links."""
    links: list[tuple[str, WebElement]] = []
    seen: set[str] = set()
    sidebar = _sidebar_module_names(driver)
    module_lower = module_name.lower().strip()

    selectors = (
        ".oxd-topbar-body-nav ul li, "
        ".oxd-topbar-body-nav-tab, "
        ".oxd-topbar-body-nav-tab-item, "
        ".orangehrm-tabs-item, "
        "[class*='topbar-body-nav'] li, "
        "[class*='topbar-body-nav'] a, "
        ".oxd-table-filter-area ~ div [role='tab']"
    )
    for el in _visible(driver.find_elements(By.CSS_SELECTOR, selectors)):
        text = _first_line(el.text or _attr(el, "aria-label") or "")
        if not text or len(text) > 50:
            continue
        key = text.lower()
        if key in seen or key in sidebar:
            continue
        if module_lower and key == module_lower:
            continue
        seen.add(key)
        links.append((text, el))
        if len(links) >= limit:
            break
    return links


def _append_field_steps(
    form_fields: list[tuple[str, str, WebElement]],
    locators: dict[str, dict[str, str]],
    loc_prefix: str,
    step_no: int,
) -> tuple[list[StepDef], int]:
    steps: list[StepDef] = []
    for j, (label, tag, fel) in enumerate(form_fields):
        try:
            _, f_by, f_val = _best_locator(fel)
            locators[f"{loc_prefix}_field_{j}"] = {"by": f_by, "value": f_val}
            if tag == "select":
                options = _get_select_options(fel)
                if options:
                    steps.append(
                        StepDef(
                            step_no,
                            "PerformSelect",
                            label,
                            options[0],
                            f_by,
                            f_val,
                            f"Selected option in '{label}'",
                        )
                    )
                    step_no += 1
            elif _attr(fel, "type").lower() == "checkbox":
                steps.append(
                    StepDef(
                        step_no,
                        "PerformClick",
                        label,
                        "",
                        f_by,
                        f_val,
                        f"Toggled checkbox '{label}'",
                    )
                )
                step_no += 1
            else:
                sample = _sample_value_for_field(label, tag, fel, j)
                action = "SetPassword" if _attr(fel, "type").lower() == "password" else "SetText"
                steps.append(
                    StepDef(
                        step_no,
                        action,
                        label,
                        sample,
                        f_by,
                        f_val,
                        f"Entered value in '{label}'",
                    )
                )
                step_no += 1
        except Exception:  # noqa: BLE001
            continue
    return steps, step_no


def _collect_search_flow(
    driver: WebDriver,
    wait: WebDriverWait,
    locators: dict[str, dict[str, str]],
    loc_prefix: str,
    step_no: int,
) -> tuple[list[StepDef], int]:
    """Search/filter on list page."""
    steps: list[StepDef] = []
    search_fields = _find_search_fields(driver)
    if not search_fields:
        return steps, step_no

    search_label, search_el = search_fields[0]
    _, s_by, s_val = _best_locator(search_el)
    locators[f"{loc_prefix}_search"] = {"by": s_by, "value": s_val}
    steps.append(
        StepDef(
            step_no,
            "SetText",
            search_label,
            "AutoTest",
            s_by,
            s_val,
            f"Entered search text in '{search_label}'",
        )
    )
    step_no += 1

    action_buttons = _find_action_buttons(driver)
    search_btn = next(
        (b for b in action_buttons if any(h in b[0].lower() for h in SEARCH_HINTS)),
        None,
    )
    if search_btn:
        btn_label, btn_el = search_btn
        _, b_by, b_val = _best_locator(btn_el)
        locators[f"{loc_prefix}_search_btn"] = {"by": b_by, "value": b_val}
        steps.append(
            StepDef(
                step_no,
                "PerformClick",
                btn_label,
                "",
                b_by,
                b_val,
                f"Searched using '{btn_label}'",
            )
        )
        step_no += 1
        if _click_by_locator(driver, b_by, b_val):
            time.sleep(1.2)
            try:
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except Exception:  # noqa: BLE001
                pass

    steps.append(
        StepDef(
            step_no,
            "Verify",
            "Search results",
            "AutoTest",
            expected="Search results or list updated",
        )
    )
    step_no += 1
    return steps, step_no


def _collect_add_save_flow(
    driver: WebDriver,
    wait: WebDriverWait,
    locators: dict[str, dict[str, str]],
    loc_prefix: str,
    step_no: int,
) -> tuple[list[StepDef], int]:
    """Add -> fill form -> Save (full CRUD create path)."""
    steps: list[StepDef] = []
    action_buttons = _find_action_buttons(driver)
    add_btn = next(
        (b for b in action_buttons if any(h in b[0].lower() for h in ADD_HINTS)),
        None,
    )
    if not add_btn:
        return steps, step_no

    add_label, add_el = add_btn
    _, add_by, add_val = _best_locator(add_el)
    locators[f"{loc_prefix}_add"] = {"by": add_by, "value": add_val}
    steps.append(
        StepDef(
            step_no,
            "PerformClick",
            add_label,
            "",
            add_by,
            add_val,
            f"Clicked '{add_label}' to open form",
        )
    )
    step_no += 1
    if not _click_by_locator(driver, add_by, add_val):
        return steps, step_no

    time.sleep(1.5)
    try:
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    except Exception:  # noqa: BLE001
        pass

    form_fields = _find_form_fields(driver, limit=12)
    field_steps, step_no = _append_field_steps(form_fields, locators, f"{loc_prefix}_add", step_no)
    steps.extend(field_steps)

    action_buttons = _find_action_buttons(driver)
    save_btn = next(
        (
            b
            for b in action_buttons
            if any(h in b[0].lower() for h in SAVE_HINTS)
            and not any(h in b[0].lower() for h in CANCEL_HINTS)
        ),
        None,
    )
    if save_btn:
        submit_label, submit_el = save_btn
        _, s_by, s_val = _best_locator(submit_el)
        btn_action = infer_action_from_button(submit_label)
        locators[f"{loc_prefix}_save"] = {"by": s_by, "value": s_val}
        steps.append(
            StepDef(
                step_no,
                btn_action,
                submit_label,
                "",
                s_by,
                s_val,
                f"Saved form via '{submit_label}'",
            )
        )
        step_no += 1
        if _click_by_locator(driver, s_by, s_val):
            time.sleep(1.5)
            try:
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except Exception:  # noqa: BLE001
                pass
        steps.append(
            StepDef(
                step_no,
                "Notification",
                "Save confirmation",
                "",
                expected="Success",
            )
        )
        step_no += 1

    return steps, step_no


def _collect_form_and_action_steps(
    driver: WebDriver,
    wait: WebDriverWait,
    locators: dict[str, dict[str, str]],
    loc_prefix: str,
    step_no: int,
) -> tuple[list[StepDef], int]:
    """Full functional flow on current page: search, add, fill, save."""
    steps: list[StepDef] = []

    search_steps, step_no = _collect_search_flow(driver, wait, locators, f"{loc_prefix}_list", step_no)
    steps.extend(search_steps)

    add_steps, step_no = _collect_add_save_flow(driver, wait, locators, loc_prefix, step_no)
    steps.extend(add_steps)

    # Inline form on page (no Add button): fill visible fields + submit
    if not add_steps:
        form_fields = _find_form_fields(driver, limit=8)
        if form_fields:
            field_steps, step_no = _append_field_steps(form_fields, locators, loc_prefix, step_no)
            steps.extend(field_steps)
            action_buttons = _find_action_buttons(driver)
            submit_btn = next(
                (
                    b
                    for b in action_buttons
                    if any(h in b[0].lower() for h in SAVE_HINTS + SEARCH_HINTS)
                ),
                None,
            )
            if submit_btn:
                submit_label, submit_el = submit_btn
                _, s_by, s_val = _best_locator(submit_el)
                btn_action = infer_action_from_button(submit_label)
                locators[f"{loc_prefix}_submit"] = {"by": s_by, "value": s_val}
                steps.append(
                    StepDef(
                        step_no,
                        btn_action,
                        submit_label,
                        "",
                        s_by,
                        s_val,
                        f"Action '{btn_action}' on '{submit_label}'",
                    )
                )
                step_no += 1

    return steps, step_no


def _build_negative_module_steps(
    positive_steps: list[StepDef],
    link_text: str,
) -> list[StepDef]:
    """Negative path: open module, submit without required data or with invalid input."""
    steps: list[StepDef] = []
    step_no = 1

    for st in positive_steps:
        if st.action in ("SetText", "SetPassword", "PerformSelect"):
            break
        steps.append(
            StepDef(
                step_no,
                st.action,
                st.object_name,
                st.input_value,
                st.locator_by,
                st.locator_value,
                st.expected,
            )
        )
        step_no += 1

    if not steps:
        return []

    steps.append(
        StepDef(
            step_no,
            "LogMessage",
            "NegativeTest",
            link_text,
            expected=f"Negative validation test for {link_text}",
        )
    )
    step_no += 1

    submit_step = next(
        (
            st
            for st in positive_steps
            if st.action in ("PerformClick", "Click", "Save")
            and any(h in st.object_name.lower() for h in SAVE_HINTS)
        ),
        None,
    )
    if submit_step:
        steps.append(
            StepDef(
                step_no,
                submit_step.action,
                submit_step.object_name,
                "",
                submit_step.locator_by,
                submit_step.locator_value,
                "Submit without required fields — expect validation error",
            )
        )
        step_no += 1
        steps.append(
            StepDef(
                step_no,
                "Verify",
                "ValidationError",
                "required",
                expected="Validation or error message displayed",
            )
        )
        return steps

    first_field = next(
        (st for st in positive_steps if st.action in ("SetText", "SetPassword")),
        None,
    )
    if first_field:
        steps.append(
            StepDef(
                step_no,
                first_field.action,
                first_field.object_name,
                "@@@INVALID###",
                first_field.locator_by,
                first_field.locator_value,
                "Enter invalid data",
            )
        )
        step_no += 1
        steps.append(
            StepDef(
                step_no,
                "Verify",
                "ValidationError",
                "invalid",
                expected="Validation or error message displayed",
            )
        )
    return steps


def _explore_module_page(
    driver: WebDriver,
    wait: WebDriverWait,
    link_text: str,
    l_by: str,
    l_val: str,
    locators: dict[str, dict[str, str]],
    loc_prefix: str,
    post_login_url: str,
) -> list[StepDef]:
    """Navigate into a module and discover full functional E2E flow."""
    from uts_engine.planning.page_intelligence import analyze_current_page

    steps: list[StepDef] = []
    step_no = 1

    try:
        _return_to_dashboard(driver, wait, post_login_url)

        # Open the module first, then record the locator that actually worked, so
        # the generated test replays the one we proved rather than a guess.
        opened_by = opened_val = ""
        for by, value in _module_open_candidates(link_text, l_by, l_val):
            if _click_by_locator(driver, by, value):
                opened_by, opened_val = by, value
                break
        if opened_by:
            l_by, l_val = opened_by, opened_val
            locators[f"{loc_prefix}_nav"] = {"by": l_by, "value": l_val}

        steps.append(
            StepDef(step_no, "PerformClick", link_text, "", l_by, l_val, f"Opened '{link_text}' module")
        )
        step_no += 1
        steps.append(StepDef(step_no, "Delay", "PageLoad", "1.5", expected="Wait after navigation"))
        step_no += 1
        steps.append(
            StepDef(step_no, "LogMessage", "ModuleStart", link_text, expected=f"Functional test: {link_text}")
        )
        step_no += 1

        if not opened_by:
            print(f"    WARN: Could not open module '{link_text}' — using nav click step only")
            return steps
        print(f"    Opened '{link_text}' via {l_by}={l_val[:60]}")

        time.sleep(1.5)
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:  # noqa: BLE001
            time.sleep(1)

        headings = _find_headings(driver)
        if headings:
            steps.append(
                StepDef(step_no, "Verify", "Page heading", headings[0], expected=headings[0])
            )
            step_no += 1

        try:
            profile = analyze_current_page(driver, link_text, "")
            steps.append(
                StepDef(
                    step_no,
                    "LogMessage",
                    "PageUnderstood",
                    profile.get("summary", link_text),
                    expected=f"Understood: {profile.get('page_type', 'page')}",
                )
            )
            step_no += 1
        except Exception:  # noqa: BLE001
            pass

        # Phase 1: list page — search + add/save on main module view
        page_steps, step_no = _collect_form_and_action_steps(
            driver, wait, locators, loc_prefix, step_no
        )
        steps.extend(page_steps)
        print(f"    Main page: {len(page_steps)} functional step(s)")

        # Phase 2: sub-tabs inside module (User Management, Add Employee, etc.)
        sub_nav = _find_sub_nav_links(driver, module_name=link_text)
        if sub_nav:
            print(f"    Sub-pages found: {', '.join(t for t, _ in sub_nav)}")
        for sub_idx, (sub_text, sub_el) in enumerate(sub_nav):
            try:
                _, sub_by, sub_val = _best_locator(sub_el)
                locators[f"{loc_prefix}_sub_{sub_idx}"] = {"by": sub_by, "value": sub_val}
                steps.append(
                    StepDef(
                        step_no,
                        "PerformClick",
                        sub_text,
                        "",
                        sub_by,
                        sub_val,
                        f"Opened '{sub_text}' sub-page",
                    )
                )
                step_no += 1
                if _click_by_locator(driver, sub_by, sub_val):
                    time.sleep(1.2)
                    try:
                        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                    except Exception:  # noqa: BLE001
                        pass
                    sub_steps, step_no = _collect_form_and_action_steps(
                        driver, wait, locators, f"{loc_prefix}_sub{sub_idx}", step_no
                    )
                    steps.extend(sub_steps)
                    try:
                        sub_profile = analyze_current_page(driver, link_text, sub_text)
                        steps.append(
                            StepDef(
                                step_no,
                                "LogMessage",
                                "PageUnderstood",
                                sub_profile.get("summary", sub_text),
                                expected=f"Understood sub-page: {sub_text}",
                            )
                        )
                        step_no += 1
                    except Exception:  # noqa: BLE001
                        pass
                    print(f"    Sub-page '{sub_text}': {len(sub_steps)} functional step(s)")
            except Exception:  # noqa: BLE001
                continue

        steps.append(
            StepDef(
                step_no,
                "Verify",
                f"{link_text} module complete",
                link_text,
                expected=f"{link_text} functional flow completed",
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"    WARN: Module exploration error for '{link_text}': {exc}")
        if not steps:
            steps.append(
                StepDef(1, "PerformClick", link_text, "", l_by, l_val, f"Open '{link_text}' module")
            )

    return steps


def discover_application(
    driver: WebDriver,
    url: str,
    username: str,
    password: str,
    app_name: str,
    automation_only: bool = False,
    description: str = "",
    role_hint: str = "",
    list_modules_only: bool = False,
    selected_modules: list[str] | None = None,
) -> DiscoveryResult:
    module_filter = parse_module_from_description(description)
    # Explicit selected_modules wins over description text
    selected = [m.strip() for m in (selected_modules or []) if m and str(m).strip()]
    if selected:
        # Treat as multi-module filter: match if ANY selected name matches
        module_filter = ""  # handled below via selected list
        print(f"  Selected modules for TC generation: {', '.join(selected)}")
    elif module_filter:
        print(f"  Module filter (from description): {module_filter}")
    elif list_modules_only:
        print("  Mode: LIST ONLY — find all modules, do not generate module TCs yet")
    else:
        print("  Module filter: (none) — generating for ALL modules")
    wait = WebDriverWait(driver, 15)
    from uts_engine.automation.selenium_session import navigate

    navigate(driver, url)
    wait.until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
    time.sleep(1)

    login_url = driver.current_url
    page_title = driver.title or app_name
    locators: dict[str, dict[str, str]] = {}

    user_el = _find_username(driver)
    pass_el = _find_password(driver)
    submit_el = _find_submit(driver)

    has_login_form = bool(user_el and pass_el)
    if not has_login_form:
        # Public site / no login page: continue without authentication.
        print("  No login form detected on this page — scanning without login (public site mode)")
        login_manual_steps = [
            StepDef(1, "Navigate", "Application URL", url, expected="Application page loads"),
            StepDef(2, "Verify", "Landing page", "", expected="Page content is visible"),
        ]
        login_auto_steps = list(login_manual_steps)

    if has_login_form:
        u_key, u_by, u_val = _best_locator(user_el)
        p_key, p_by, p_val = _best_locator(pass_el)
        user_label = _label_for(user_el)
        pass_label = _label_for(pass_el)
        locators["username"] = {"by": u_by, "value": u_val}
        locators["password"] = {"by": p_by, "value": p_val}

        submit_key = "login_button"
        submit_label = "Login"
        s_by = s_val = ""
        if submit_el:
            s_key, s_by, s_val = _best_locator(submit_el)
            submit_key = s_key
            submit_label = (submit_el.text or _attr(submit_el, "value") or "Login").strip() or "Login"
            locators[submit_key] = {"by": s_by, "value": s_val}

        login_manual_steps = [
            StepDef(1, "Navigate", "Application URL", url, expected="Login page loads"),
        ]
        login_auto_steps = list(login_manual_steps)
        step_no = 2

        # Xpedite Test Farm: Language + Role appear before username
        _lang_el, selected_lang = perform_language_selection(driver, "English")
        if selected_lang and _lang_el:
            _, l_by, l_val = _best_locator(_lang_el)
            locators["language"] = {"by": l_by, "value": l_val}
            lang_step = StepDef(
                step_no,
                "PerformSelect",
                "Language",
                selected_lang,
                l_by,
                l_val,
                f"Language '{selected_lang}' selected",
            )
            login_manual_steps.append(lang_step)
            login_auto_steps.append(lang_step)
            step_no += 1
            print(f"  Language dropdown: selected '{selected_lang}'")

        _role_el_early, selected_role_early = perform_role_selection(
            driver, username, role_hint, wait_timeout=5
        )
        if selected_role_early and _role_el_early:
            _, r_by, r_val = _best_locator(_role_el_early)
            locators["role"] = {"by": r_by, "value": r_val}
            role_step = StepDef(
                step_no,
                "PerformSelect",
                "Role",
                selected_role_early,
                r_by,
                r_val,
                f"Role '{selected_role_early}' selected",
            )
            login_manual_steps.append(role_step)
            login_auto_steps.append(role_step)
            step_no += 1
            print(f"  Role dropdown: selected '{selected_role_early}'")

        login_manual_steps.append(
            StepDef(step_no, "SetText", user_label, username, u_by, u_val, "Username entered")
        )
        login_auto_steps.append(login_manual_steps[-1])
        step_no += 1

        fill_username_and_trigger_role(driver, user_el, username)
        # Re-select role if username entry refreshes/enables the dropdown
        if "role" not in locators:
            _role_el, selected_role = perform_role_selection(driver, username, role_hint)
            if selected_role:
                role_el = find_role_select(driver)
                if role_el:
                    _, r_by, r_val = _best_locator(role_el)
                else:
                    r_by, r_val = "id", "dllRole"
                locators["role"] = {"by": r_by, "value": r_val}
                role_step = StepDef(
                    step_no,
                    "PerformSelect",
                    "Role",
                    selected_role,
                    r_by,
                    r_val,
                    f"Role '{selected_role}' selected",
                )
                login_manual_steps.append(role_step)
                login_auto_steps.append(role_step)
                step_no += 1
                print(f"  Role dropdown: selected '{selected_role}'")

        login_manual_steps.append(
            StepDef(step_no, "SetText", pass_label, "********", p_by, p_val, "Password entered")
        )
        login_auto_steps.append(login_manual_steps[-1])
        step_no += 1

        if submit_el:
            login_manual_steps.append(
                StepDef(
                    step_no,
                    "PerformClick",
                    submit_label,
                    "",
                    s_by,
                    s_val,
                    "User lands on home/dashboard",
                )
            )
            login_auto_steps.append(login_manual_steps[-1])
            step_no += 1
        login_manual_steps.append(
            StepDef(step_no, "Verify", "Post-login page", "", expected="Dashboard or home visible")
        )
        login_auto_steps.append(login_manual_steps[-1])

        # Perform login to discover post-login UI (username + role already set above)
        time.sleep(1)
        pass_el = _find_password(driver)
        submit_el = _find_submit(driver)
        if pass_el:
            pass_el.clear()
            pass_el.send_keys(password)
        if submit_el:
            submit_el.click()
        elif pass_el:
            pass_el.submit()
        try:
            wait.until(
                lambda d: "login" not in d.current_url.lower()
                or "dashboard" in d.current_url.lower()
                or "NewDashboard" in d.current_url
            )
        except Exception:  # noqa: BLE001
            time.sleep(2)
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

    post_login_url = driver.current_url
    try:
        wait.until(lambda d: len(_find_nav_links(d)) > 0)
    except Exception:  # noqa: BLE001
        pass  # genuinely empty app — fall through with zero modules
    headings = _find_headings(driver)
    nav_links = _find_nav_links(driver)
    form_fields = _find_form_fields(driver)

    explore_manual: list[StepDef] = [
        StepDef(1, "Verify", "Logged-in page", "", expected=f"URL: {post_login_url}"),
    ]
    explore_auto: list[StepDef] = [
        StepDef(1, "Verify", "Logged-in page", post_login_url, expected="URL changed after login"),
    ]
    if headings:
        explore_manual.append(StepDef(2, "Verify", "Page heading", headings[0], expected=headings[0]))
        explore_auto.append(StepDef(2, "Verify", "Page heading", headings[0], expected=headings[0]))

    step_idx = len(explore_manual) + 1
    for i, (link_text, el) in enumerate(nav_links[:3]):
        l_key, l_by, l_val = _best_locator(el)
        locators[f"nav_{i+1}"] = {"by": l_by, "value": l_val}
        explore_manual.append(
            StepDef(step_idx, "PerformClick", link_text, "", l_by, l_val, f"'{link_text}' opens")
        )
        explore_auto.append(StepDef(step_idx, "PerformClick", link_text, "", l_by, l_val, f"Clicked '{link_text}'"))
        step_idx += 1

    if form_fields:
        for j, (label, _tag, fel) in enumerate(form_fields[:3]):
            f_key, f_by, f_val = _best_locator(fel)
            locators[f"field_{j+1}"] = {"by": f_by, "value": f_val}
            explore_manual.append(
                StepDef(step_idx, "SetText", label, f"<{label}>", f_by, f_val, f"{label} accepts input")
            )
            explore_auto.append(
                StepDef(step_idx, "SetText", label, f"test_{j+1}", f_by, f_val, f"Entered test value in {label}")
            )
            step_idx += 1

    def _with_login(login_base: list[StepDef], extra_steps: list[StepDef]) -> list[StepDef]:
        """Every test case must include the full login flow."""
        combined = list(login_base)
        start = len(combined) + 1
        for i, s in enumerate(extra_steps):
            combined.append(
                StepDef(
                    step_no=start + i,
                    action=s.action,
                    object_name=s.object_name,
                    input_value=s.input_value,
                    locator_by=s.locator_by,
                    locator_value=s.locator_value,
                    expected=s.expected,
                )
            )
        return combined

    if automation_only:
        scenarios = [
            ScenarioDef(
                "TC_AUTO_01",
                "automation",
                (
                    f"Automated login — {app_name}"
                    if has_login_form
                    else f"Open application — {app_name}"
                ),
                login_auto_steps,
                module="Login" if has_login_form else "Core",
            ),
        ]
        auto_idx = 2

        base_explore_extra = [
            StepDef(
                1,
                "Verify",
                "Logged-in page" if has_login_form else "Landing page",
                post_login_url,
                expected="URL changed after login" if has_login_form else "Page loaded",
            ),
        ]
        if headings:
            base_explore_extra.append(
                StepDef(2, "Verify", "Page heading", headings[0], expected=headings[0])
            )
        scenarios.append(
            ScenarioDef(
                f"TC_AUTO_{auto_idx:02d}",
                "automation",
                (
                    f"Post-login validation — {app_name}"
                    if has_login_form
                    else f"Landing page validation — {app_name}"
                ),
                _with_login(login_auto_steps, base_explore_extra),
                module="Core",
            )
        )
        auto_idx += 1

        print(f"  Modules / nav items found: {len(nav_links)}")
        for link_text, _ in nav_links:
            print(f"    - {link_text}")

        # Always build full module catalog with locators (for list + later generate)
        modules_catalog = []
        for i, (link_text, el) in enumerate(nav_links):
            l_key, l_by, l_val = _best_locator(el)
            # Record what was actually observed on this page. This used to store
            # _module_nav_xpath() — an OrangeHRM-only selector — discarding the
            # real locator it had just computed. Every downstream consumer then
            # inherited a selector that cannot match any other application, which
            # is why module exploration reported "could not open" everywhere.
            if not l_val:
                l_by, l_val = "xpath", _module_nav_xpath(link_text)
            locators[f"nav_{i+1}"] = {"by": l_by, "value": l_val}
            modules_catalog.append(
                {
                    "id": slugify_module(link_text),
                    "name": link_text,
                    "locator": {"by": l_by, "value": l_val},
                    "scenario_ids": [],
                }
            )

        if list_modules_only:
            # CYCLE 1: modules list only — NO test cases, NO deep page explore
            print("  CYCLE 1 DONE — modules listed only.")
            print("  Test cases NOT created yet.")
            print("  Next: set module in app-input.json, then RUN.bat again (Cycle 2).")
            return DiscoveryResult(
                url=url,
                username=username,
                app_name=app_name,
                page_title=page_title,
                discovered_at=datetime.now().isoformat(timespec="seconds"),
                login_url=login_url,
                post_login_url=post_login_url,
                scenarios=scenarios,
                locators=locators,
                modules=modules_catalog,
                pages=[],
            )

        # Step 2: generate TCs for selected modules (empty selected = ALL)
        def _nav_selected(link_text: str) -> bool:
            if selected:
                return any(
                    matches_module(link_text, s) or s.lower() == link_text.lower()
                    for s in selected
                )
            if module_filter:
                return matches_module(link_text, module_filter)
            return True  # nothing given → ALL modules

        matched_nav = [(t, el) for t, el in nav_links if _nav_selected(t)]
        if (selected or module_filter) and not matched_nav:
            print("  INFO: No nav links matched selection — generating 0 module TCs")
            matched_nav = []

        if selected:
            print(f"  Generating TCs for {len(matched_nav)} selected module(s)")
        else:
            print(f"  Generating TCs for ALL {len(matched_nav)} module(s)")

        from uts_engine.planning.page_intelligence import (
            save_page_map,
            scan_all_application_pages,
            write_page_map_html,
        )

        scan_catalog = [
            m for m in modules_catalog
            if any(m["name"] == t for t, _ in matched_nav)
        ]
        pages = scan_all_application_pages(
            driver, wait, scan_catalog, post_login_url
        )
        save_page_map(pages, app_name=app_name, url=url)
        write_page_map_html(pages, app_name=app_name, url=url)

        module_map: dict[str, list[str]] = {}

        for i, (link_text, el) in enumerate(matched_nav):
            # reuse catalog locator if present
            loc = next((m["locator"] for m in modules_catalog if m["name"] == link_text), None)
            if loc:
                l_by, l_val = loc["by"], loc["value"]
            else:
                l_by, l_val = "xpath", _module_nav_xpath(link_text)

            print(f"  Exploring module '{link_text}' — forms, fields, buttons...")
            try:
                module_steps = _explore_module_page(
                    driver,
                    wait,
                    link_text,
                    l_by,
                    l_val,
                    locators,
                    f"mod_{i + 1}",
                    post_login_url,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    WARN: Skipping deep explore for '{link_text}': {exc}")
                module_steps = [
                    StepDef(
                        1,
                        "PerformClick",
                        link_text,
                        "",
                        l_by,
                        l_val,
                        f"Clicked '{link_text}'",
                    )
                ]
            if not module_steps:
                module_steps = [
                    StepDef(
                        1,
                        "PerformClick",
                        link_text,
                        "",
                        l_by,
                        l_val,
                        f"Clicked '{link_text}'",
                    )
                ]

            tc_id_pos = f"TC_POS_{auto_idx:02d}"
            scenarios.append(
                ScenarioDef(
                    tc_id_pos,
                    "positive",
                    f"{link_text} — positive flow — {app_name}",
                    _with_login(login_auto_steps, module_steps),
                    module=link_text,
                )
            )
            module_map.setdefault(link_text, []).append(tc_id_pos)
            print(f"    -> {tc_id_pos}: {len(module_steps)} step(s) [positive]")

            neg_steps = _build_negative_module_steps(module_steps, link_text)
            if neg_steps:
                tc_id_neg = f"TC_NEG_{auto_idx:02d}"
                scenarios.append(
                    ScenarioDef(
                        tc_id_neg,
                        "negative",
                        f"{link_text} — negative validation — {app_name}",
                        _with_login(login_auto_steps, neg_steps),
                        module=link_text,
                    )
                )
                module_map.setdefault(link_text, []).append(tc_id_neg)
                print(f"    -> {tc_id_neg}: {len(neg_steps)} step(s) [negative]")
            auto_idx += 1

        # Attach scenario_ids back onto catalog
        for m in modules_catalog:
            m["scenario_ids"] = list(module_map.get(m["name"], []))

        return DiscoveryResult(
            url=url,
            username=username,
            app_name=app_name,
            page_title=page_title,
            discovered_at=datetime.now().isoformat(timespec="seconds"),
            login_url=login_url,
            post_login_url=post_login_url,
            scenarios=scenarios,
            locators=locators,
            modules=modules_catalog,
            pages=pages,
        )
    else:
        scenarios = [
            ScenarioDef("TC_MAN_01", "manual", f"Login to {app_name}", login_manual_steps, module="Login"),
            ScenarioDef(
                "TC_AUTO_01",
                "automation",
                f"Automated login — {app_name}",
                login_auto_steps,
                module="Login",
            ),
            ScenarioDef(
                "TC_MAN_02",
                "manual",
                f"Explore {app_name} after login",
                _with_login(login_manual_steps, explore_manual),
                module="Core",
            ),
            ScenarioDef(
                "TC_AUTO_02",
                "automation",
                f"Post-login validation — {app_name}",
                _with_login(login_auto_steps, explore_auto),
                module="Core",
            ),
        ]
        modules_catalog = []

    return DiscoveryResult(
        url=url,
        username=username,
        app_name=app_name,
        page_title=page_title,
        discovered_at=datetime.now().isoformat(timespec="seconds"),
        login_url=login_url,
        post_login_url=post_login_url,
        scenarios=scenarios,
        locators=locators,
        modules=modules_catalog,
    )
