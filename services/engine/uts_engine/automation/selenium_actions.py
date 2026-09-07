"""Selenium action helpers — wait, click, type, select, verify."""

from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from uts_engine.automation.selenium_session import get_driver, load_selenium_config, screenshot_on_failure

_BY_MAP = {
    "id": By.ID,
    "name": By.NAME,
    "css": By.CSS_SELECTOR,
    "xpath": By.XPATH,
    "class": By.CLASS_NAME,
    "tag": By.TAG_NAME,
    "link_text": By.LINK_TEXT,
}


def _locator(key: str) -> tuple[str, str]:
    cfg = load_selenium_config()
    loc = cfg["locators"][key]
    by = _BY_MAP.get(loc["by"].lower(), By.ID)
    return by, loc["value"]


def _wait():
    secs = int(load_selenium_config().get("explicit_wait_seconds", 15))
    return WebDriverWait(get_driver(), secs)


def wait_visible(key: str):
    by, value = _locator(key)
    return _wait().until(EC.visibility_of_element_located((by, value)))


def wait_clickable(key: str):
    by, value = _locator(key)
    return _wait().until(EC.element_to_be_clickable((by, value)))


def click(key: str) -> None:
    el = wait_clickable(key)
    el.click()


def type_text(key: str, text: str, clear: bool = True) -> None:
    el = wait_visible(key)
    if clear:
        el.clear()
    el.send_keys(text)


def select_by_visible_text(key: str, text: str) -> None:
    el = wait_visible(key)
    Select(el).select_by_visible_text(text)


def is_visible(key: str) -> bool:
    try:
        wait_visible(key)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_text(key: str) -> str:
    return wait_visible(key).text.strip()


def page_title_contains(text: str) -> bool:
    return text.lower() in get_driver().title.lower()


def current_url() -> str:
    return get_driver().current_url


def safe_action(key: str, action_fn, fail_label: str) -> tuple[bool, str]:
    try:
        action_fn()
        return True, fail_label.replace("FAIL", "OK") if "FAIL" in fail_label else fail_label
    except Exception as exc:  # noqa: BLE001
        shot = screenshot_on_failure(key)
        msg = f"{fail_label}: {exc}"
        if shot:
            msg += f" | screenshot: {shot}"
        return False, msg
