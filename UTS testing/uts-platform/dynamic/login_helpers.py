"""Shared login helpers for ASP.NET / Xpedite-style role and language dropdowns."""

from __future__ import annotations

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import Select, WebDriverWait

ROLE_SELECT_HINTS = ("role", "dllrole", "cborole", "userrole", "ddlrole")
LANGUAGE_HINTS = ("lang", "language", "culture", "locale", "اللغة")
ROLE_OPTION_HINTS = ("admin", "tester", "guest", "user", "manager", "developer")
LANGUAGE_OPTION_HINTS = ("english", "arabic", "العربية", "hindi", "french", "spanish")


def derive_role_hint(username: str, role_config: str = "") -> str:
    if role_config and role_config.strip():
        return role_config.strip()
    if "manager" in username.lower():
        return "manager"
    if "admin" in username.lower():
        return "admin"
    if "tester" in username.lower():
        return "tester"
    return "Tester"


def _visible_selects(driver: WebDriver) -> list[WebElement]:
    out: list[WebElement] = []
    for el in driver.find_elements(By.CSS_SELECTOR, "select"):
        try:
            if not el.is_displayed():
                continue
            style = (el.get_attribute("style") or "").lower().replace(" ", "")
            if "display:none" in style:
                continue
            out.append(el)
        except Exception:  # noqa: BLE001
            continue
    return out


def _select_meta(el: WebElement) -> tuple[str, list[str]]:
    key = f"{el.get_attribute('id') or ''} {el.get_attribute('name') or ''}".lower()
    options: list[str] = []
    try:
        for opt in Select(el).options:
            text = (opt.text or "").strip()
            if text:
                options.append(text)
    except Exception:  # noqa: BLE001
        pass
    return key, options


def _looks_like_language(key: str, options: list[str]) -> bool:
    if any(h in key for h in LANGUAGE_HINTS):
        return True
    joined = " ".join(options).lower()
    hits = sum(1 for h in LANGUAGE_OPTION_HINTS if h in joined)
    return hits >= 1 and not any(h in joined for h in ("admin", "tester"))


def _looks_like_role(key: str, options: list[str]) -> bool:
    if any(h in key for h in ROLE_SELECT_HINTS):
        return True
    if _looks_like_language(key, options):
        return False
    joined = " ".join(options).lower()
    return any(h in joined for h in ROLE_OPTION_HINTS)


def find_language_select(driver: WebDriver) -> WebElement | None:
    for el in _visible_selects(driver):
        key, options = _select_meta(el)
        if _looks_like_language(key, options):
            return el
    return None


def find_role_select(driver: WebDriver) -> WebElement | None:
    candidates = _visible_selects(driver)
    for el in candidates:
        key, options = _select_meta(el)
        if any(h in key for h in ROLE_SELECT_HINTS):
            return el
    for el in candidates:
        key, options = _select_meta(el)
        if _looks_like_role(key, options):
            return el
    # Last resort: first non-language select
    for el in candidates:
        key, options = _select_meta(el)
        if not _looks_like_language(key, options):
            return el
    return None


def wait_role_select_enabled(driver: WebDriver, timeout: float = 15) -> WebElement | None:
    def _enabled(drv: WebDriver):
        el = find_role_select(drv)
        if el and not el.get_attribute("disabled"):
            return el
        return False

    try:
        return WebDriverWait(driver, timeout).until(_enabled)
    except Exception:  # noqa: BLE001
        return None


def pick_role_option(select_el: WebElement, hint: str) -> str:
    sel = Select(select_el)
    options: list[str] = []
    for opt in sel.options:
        text = (opt.text or "").strip()
        if not text or text.lower().startswith("select"):
            continue
        options.append(text)
    if not options:
        raise ValueError("No selectable role options found")

    hint_lower = hint.lower() if hint else ""
    if hint_lower:
        for text in options:
            if hint_lower in text.lower():
                sel.select_by_visible_text(text)
                return text
        for text in options:
            if any(tok in text.lower() for tok in hint_lower.split()):
                sel.select_by_visible_text(text)
                return text

    # Prefer Tester for Xpedite Test Farm when no hint
    for preferred in ("Tester", "Admin", "User"):
        for text in options:
            if preferred.lower() in text.lower():
                sel.select_by_visible_text(text)
                return text

    sel.select_by_visible_text(options[0])
    return options[0]


def pick_language_option(select_el: WebElement, hint: str = "English") -> str:
    sel = Select(select_el)
    options = [(opt.text or "").strip() for opt in sel.options if (opt.text or "").strip()]
    if not options:
        return ""
    hint_lower = (hint or "English").lower()
    for text in options:
        if hint_lower in text.lower():
            sel.select_by_visible_text(text)
            return text
    sel.select_by_visible_text(options[0])
    return options[0]


def fill_username_and_trigger_role(driver: WebDriver, user_el: WebElement, username: str) -> None:
    user_el.clear()
    user_el.send_keys(username)
    user_el.send_keys(Keys.TAB)
    time.sleep(1.5)


def perform_language_selection(
    driver: WebDriver,
    language_hint: str = "English",
) -> tuple[WebElement | None, str]:
    lang_el = find_language_select(driver)
    if not lang_el:
        return None, ""
    selected = pick_language_option(lang_el, language_hint)
    time.sleep(0.5)
    return lang_el, selected


def perform_role_selection(
    driver: WebDriver,
    username: str,
    role_hint: str = "",
    wait_timeout: float = 15,
) -> tuple[WebElement | None, str]:
    """Select role if dropdown appears (Xpedite: before or after username)."""
    hint = derive_role_hint(username, role_hint)
    role_el = wait_role_select_enabled(driver, wait_timeout)
    if not role_el:
        return None, ""
    selected = pick_role_option(role_el, hint)
    time.sleep(1.0)
    return role_el, selected
