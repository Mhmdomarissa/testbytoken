"""Logout and fresh-login between automation test cases."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from selenium.webdriver.common.by import By

from automation.selenium_session import get_driver, load_selenium_config, navigate
from dynamic.login_helpers import fill_username_and_trigger_role, perform_role_selection

if TYPE_CHECKING:
    from automation.base import ExecutionLogger
    from dynamic.discovery import DiscoveryResult

BY_MAP = {
    "id": By.ID,
    "name": By.NAME,
    "css": By.CSS_SELECTOR,
    "xpath": By.XPATH,
    "class": By.CLASS_NAME,
}

LOGOUT_HINTS = ("logout", "log out", "sign out", "signout")


def _log(logger: ExecutionLogger | None, message: str) -> None:
    if logger:
        logger.info(message)
    else:
        print(message)


def _find_logout_element():
    driver = get_driver()
    selectors = [
        (By.CSS_SELECTOR, "a[href*='logout' i], a[href*='Logout']"),
        (By.CSS_SELECTOR, "[id*='logout' i], [name*='logout' i]"),
        (By.CSS_SELECTOR, "button[id*='logout' i], input[value*='Logout' i]"),
    ]
    for by, value in selectors:
        for el in driver.find_elements(by, value):
            if el.is_displayed():
                return el

    for el in driver.find_elements(By.CSS_SELECTOR, "a, button, input[type='submit'], input[type='button']"):
        label = " ".join(
            filter(
                None,
                [
                    (el.text or "").strip(),
                    el.get_attribute("value") or "",
                    el.get_attribute("id") or "",
                    el.get_attribute("title") or "",
                ],
            )
        ).lower()
        if any(hint in label for hint in LOGOUT_HINTS):
            if el.is_displayed():
                return el

    cfg = load_selenium_config()
    logout_loc = cfg.get("locators", {}).get("logout_button")
    if logout_loc:
        by = BY_MAP.get(logout_loc.get("by", "id"), By.ID)
        el = driver.find_element(by, logout_loc["value"])
        if el.is_displayed():
            return el
    return None


def logout_and_reset(login_url: str, logger: ExecutionLogger | None = None) -> bool:
    """Logout if possible, then return browser to login page. Always continues."""
    driver = get_driver()
    _log(logger, "SESSION RESET: logging out and returning to login page...")

    try:
        logout_el = _find_logout_element()
        if logout_el:
            logout_el.click()
            time.sleep(1)
            _log(logger, "SESSION RESET: clicked logout control")
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"SESSION RESET: logout control not used ({exc})")

    try:
        driver.delete_all_cookies()
    except Exception:  # noqa: BLE001
        pass

    try:
        navigate(driver, login_url)
        time.sleep(1.2)
        _log(logger, f"SESSION RESET: navigated to login URL — {driver.current_url}")
        return True
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"SESSION RESET: failed to open login URL — {exc}")
        return False


def perform_login_from_locators(
    locators: dict,
    username: str,
    password: str,
    login_url: str,
    logger: ExecutionLogger | None = None,
    role_hint: str = "",
) -> bool:
    """Fresh login using discovered/configured locators."""
    driver = get_driver()
    _log(logger, "SESSION RESET: performing fresh login...")

    try:
        if driver.current_url.split("?")[0] != login_url.split("?")[0]:
            navigate(driver, login_url)
            time.sleep(1)

        user = locators.get("username")
        pwd = locators.get("password")
        if not user or not pwd:
            _log(logger, "SESSION RESET: username/password locators missing")
            return False

        user_by = BY_MAP.get(user["by"], By.ID)
        pwd_by = BY_MAP.get(pwd["by"], By.ID)
        user_el = driver.find_element(user_by, user["value"])
        pwd_el = driver.find_element(pwd_by, pwd["value"])

        if user_el.is_displayed():
            fill_username_and_trigger_role(driver, user_el, username)

        role_loc = locators.get("role")
        if role_loc:
            role_el, selected = perform_role_selection(driver, username, role_hint)
            if selected:
                _log(logger, f"SESSION RESET: selected role '{selected}'")
        else:
            perform_role_selection(driver, username, role_hint)

        pwd_el = driver.find_element(pwd_by, pwd["value"])
        if pwd_el.is_displayed():
            pwd_el.clear()
            pwd_el.send_keys(password)

        submit = None
        for key, loc in locators.items():
            if key in ("username", "password", "role"):
                continue
            if "login" in key.lower() or loc.get("by") == "id" and "login" in loc.get("value", "").lower():
                submit = loc
                break
        if submit is None:
            for key, loc in locators.items():
                if key.startswith("el_") and key not in ("username", "password", "role"):
                    submit = loc
                    break

        if submit:
            by = BY_MAP.get(submit["by"], By.ID)
            driver.find_element(by, submit["value"]).click()
        else:
            pwd_el.submit()

        time.sleep(1.5)
        _log(logger, f"SESSION RESET: login submitted — now at {driver.current_url}")
        return True
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"SESSION RESET: login failed — {exc}")
        return False


def perform_login_from_discovery(
    discovery: DiscoveryResult,
    password: str,
    logger: ExecutionLogger | None = None,
    role_hint: str = "",
) -> bool:
    return perform_login_from_locators(
        discovery.locators,
        discovery.username,
        password,
        discovery.login_url,
        logger,
        role_hint=role_hint,
    )


def perform_static_login(logger: ExecutionLogger | None = None) -> bool:
    from automation.base import load_test_data

    data = load_test_data()
    creds = data["credentials"]
    cfg = load_selenium_config()
    locators = cfg.get("locators", {})
    login_url = cfg.get("base_url", "demo")
    if login_url.lower() == "demo":
        from automation.selenium_session import resolve_base_url

        login_url = resolve_base_url()
    return perform_login_from_locators(locators, creds["username"], creds["password"], login_url, logger)


def prepare_fresh_session(
    discovery: DiscoveryResult,
    password: str,
    logger: ExecutionLogger | None = None,
    role_hint: str = "",
) -> None:
    """Logout + login before a new automation scenario."""
    logout_and_reset(discovery.login_url, logger)
    perform_login_from_discovery(discovery, password, logger, role_hint=role_hint)


def teardown_after_test(discovery: DiscoveryResult, logger: ExecutionLogger | None = None) -> None:
    """Always logout after each test case so next scenario starts clean."""
    logout_and_reset(discovery.login_url, logger)


def teardown_static(login_url: str | None = None, logger: ExecutionLogger | None = None) -> None:
    if not login_url:
        from automation.selenium_session import resolve_base_url

        login_url = resolve_base_url()
    logout_and_reset(login_url, logger)


def prepare_static_fresh_session(logger: ExecutionLogger | None = None) -> None:
    teardown_static(logger=logger)
    perform_static_login(logger)
