"""Logout and fresh-login between automation test cases."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from selenium.webdriver.common.by import By

from uts_engine.automation.selenium_session import get_driver, load_selenium_config, navigate
from uts_engine.discovery.login_helpers import fill_username_and_trigger_role, perform_role_selection

if TYPE_CHECKING:
    from uts_engine.automation.base import ExecutionLogger
    from uts_engine.discovery.discovery import DiscoveryResult

BY_MAP = {
    "id": By.ID,
    "name": By.NAME,
    "css": By.CSS_SELECTOR,
    "xpath": By.XPATH,
    "class": By.CLASS_NAME,
}

LOGOUT_HINTS = ("logout", "log out", "sign out", "signout")

# Generic dropdown/avatar triggers that commonly gate a logout link behind a
# second click — not one app's class name, a list of common shapes. OrangeHRM
# needs this (.oxd-userdropdown-tab); kept broad on purpose so other apps that
# hide logout the same way stand a chance too.
USER_MENU_HINTS_CSS = (
    "[class*='userdropdown' i]",
    "[class*='user-dropdown' i]",
    "[class*='user-menu' i]",
    "[class*='usermenu' i]",
    "[class*='avatar' i]",
    "[aria-haspopup='true'][class*='user' i]",
    "[aria-haspopup='menu']",
)


def _log(logger: ExecutionLogger | None, message: str) -> None:
    if logger:
        logger.info(message)
    else:
        print(message)


def _direct_logout_scan():
    """Logout link/button already present without opening any menu first."""
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

    for el in driver.find_elements(
        By.CSS_SELECTOR, "a, button, input[type='submit'], input[type='button'], [role='menuitem']"
    ):
        label = " ".join(
            filter(
                None,
                [
                    (el.text or "").strip(),
                    el.get_attribute("value") or "",
                    el.get_attribute("id") or "",
                    el.get_attribute("title") or "",
                    el.get_attribute("aria-label") or "",
                ],
            )
        ).lower()
        if any(hint in label for hint in LOGOUT_HINTS):
            if el.is_displayed():
                return el
    return None


def _crawl_sourced_logout(locators: dict | None):
    """A logout locator the crawl itself recorded, by name — same pattern
    every other assertion/step now prefers over a guess. Nothing calls the
    crawl to look for this yet, so this is empty in practice today; kept so
    that once it does, this path picks it up with no further change here."""
    if not locators:
        return None
    driver = get_driver()
    for key, loc in locators.items():
        if not isinstance(loc, dict):
            continue
        if not any(h in key.lower() for h in ("logout", "sign_out", "signout", "log_out")):
            continue
        by = BY_MAP.get(loc.get("by", "id"), By.ID)
        value = loc.get("value", "")
        if not value:
            continue
        try:
            for el in driver.find_elements(by, value):
                if el.is_displayed():
                    return el
        except Exception:  # noqa: BLE001
            continue
    return None


def _find_logout_element(locators: dict | None = None):
    driver = get_driver()

    el = _crawl_sourced_logout(locators)
    if el:
        return el

    el = _direct_logout_scan()
    if el:
        return el

    # Two-step: open a user-menu/avatar dropdown, then look again — this is
    # what OrangeHRM (and most apps that hide logout behind a profile menu)
    # actually needs; the direct scan above never sees the link because it
    # isn't in the DOM as visible until the trigger is clicked.
    for selector in USER_MENU_HINTS_CSS:
        for trigger in driver.find_elements(By.CSS_SELECTOR, selector):
            if not trigger.is_displayed():
                continue
            try:
                trigger.click()
                time.sleep(0.5)
            except Exception:  # noqa: BLE001
                continue
            el = _direct_logout_scan()
            if el:
                return el

    # Fixture-config fallback — guarded. This used to call find_element()
    # directly, which raises NoSuchElementException on any app but the
    # bundled demo fixture; that exception was only ever caught by the
    # caller's broad try/except, which is what let a real crash read as a
    # harmless log line. find_elements() here never raises.
    cfg = load_selenium_config()
    logout_loc = cfg.get("locators", {}).get("logout_button")
    if logout_loc:
        by = BY_MAP.get(logout_loc.get("by", "id"), By.ID)
        for el in driver.find_elements(by, logout_loc.get("value", "")):
            if el.is_displayed():
                return el
    return None


def _confirm_logged_out(login_url: str) -> tuple[bool, str]:
    """A logout that can't be confirmed is the same disease as a verify that
    silently passes (E1/E3) — never assume the click worked."""
    driver = get_driver()
    current = driver.current_url.split("?")[0].rstrip("/")
    expected = login_url.split("?")[0].rstrip("/")
    if current == expected:
        return True, f"URL matches the login page ({driver.current_url})"
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
            if el.is_displayed():
                return True, "a visible password field is present"
    except Exception:  # noqa: BLE001
        pass
    return False, f"expected login URL {login_url} or a visible login form; still on {driver.current_url}"


def logout_and_reset(
    login_url: str, logger: ExecutionLogger | None = None, locators: dict | None = None
) -> bool:
    """Logout, return to the login page, and VERIFY it actually worked.

    Returns False (not just "no exception") when logout cannot be confirmed
    — a caller that ignores this return value and proceeds anyway is exactly
    how a session silently carried over between test cases before this."""
    driver = get_driver()
    _log(logger, "SESSION RESET: logging out and returning to login page...")

    try:
        logout_el = _find_logout_element(locators)
        if logout_el:
            logout_el.click()
            time.sleep(1)
            _log(logger, "SESSION RESET: clicked logout control")
        else:
            _log(logger, "SESSION RESET: no logout control found by any cascade")
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"SESSION RESET: logout control not used ({exc})")

    try:
        driver.delete_all_cookies()
    except Exception:  # noqa: BLE001
        pass

    try:
        navigate(driver, login_url)
        time.sleep(1.2)
    except Exception as exc:  # noqa: BLE001
        _log(logger, f"SESSION RESET: FAIL — failed to open login URL — {exc}")
        return False

    confirmed, detail = _confirm_logged_out(login_url)
    if confirmed:
        _log(logger, f"SESSION RESET: confirmed logged out — {detail}")
        return True
    _log(logger, f"SESSION RESET: FAIL — could not confirm logout — {detail}")
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
    from uts_engine.automation.base import load_test_data

    data = load_test_data()
    creds = data["credentials"]
    cfg = load_selenium_config()
    locators = cfg.get("locators", {})
    login_url = cfg.get("base_url", "demo")
    if login_url.lower() == "demo":
        from uts_engine.automation.selenium_session import resolve_base_url

        login_url = resolve_base_url()
    return perform_login_from_locators(locators, creds["username"], creds["password"], login_url, logger)


def prepare_fresh_session(
    discovery: DiscoveryResult,
    password: str,
    logger: ExecutionLogger | None = None,
    role_hint: str = "",
) -> bool:
    """Logout + login before a new automation scenario.

    Returns False if logout could not be confirmed OR the subsequent login
    failed — the caller must not run the next scenario as though it were
    starting from a clean, authenticated state when this is False."""
    logged_out = logout_and_reset(discovery.login_url, logger, locators=discovery.locators)
    logged_in = perform_login_from_discovery(discovery, password, logger, role_hint=role_hint)
    return logged_out and logged_in


def teardown_after_test(discovery: DiscoveryResult, logger: ExecutionLogger | None = None) -> bool:
    """Always logout after each test case so next scenario starts clean."""
    return logout_and_reset(discovery.login_url, logger, locators=discovery.locators)


def teardown_static(login_url: str | None = None, logger: ExecutionLogger | None = None) -> bool:
    if not login_url:
        from uts_engine.automation.selenium_session import resolve_base_url

        login_url = resolve_base_url()
    return logout_and_reset(login_url, logger)


def prepare_static_fresh_session(logger: ExecutionLogger | None = None) -> None:
    teardown_static(logger=logger)
    perform_static_login(logger)
