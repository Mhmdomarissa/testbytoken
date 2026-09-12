"""D8 regression: a logout that can't be confirmed must FAIL, not silently
continue as if the session were clean.

Root cause this guards against: session_reset.py's old _find_logout_element()
only checked a fixture-shaped config locator as its last resort, crashed
(unguarded find_element()) when that didn't match either, and the caller's
broad except swallowed the crash into a harmless-looking log line —
logout_and_reset() then returned True regardless of whether anything actually
happened. The same disease as a verify that silently passes (E1/E3).

No browser required.
"""

from __future__ import annotations

from tests.fakes import FakeDriver, FakeElement
from uts_engine.automation import session_reset as session_reset_module
from uts_engine.discovery.discovery import DiscoveryResult, ScenarioDef, StepDef


LOGIN_URL = "https://app.test/auth/login"
DASHBOARD_URL = "https://app.test/dashboard"


def _still_authenticated_driver() -> FakeDriver:
    """No logout control anywhere (direct scan, user-menu cascade, and the
    fixture config fallback all find nothing), and the app itself still
    bounces a login-page visit straight to the dashboard — exactly the
    OrangeHRM-shaped case a real logout has to actually clear."""
    return FakeDriver(
        current_url=DASHBOARD_URL,
        still_authenticated_redirect=(LOGIN_URL, DASHBOARD_URL),
    )


def test_logout_and_reset_fails_when_nothing_confirms_logout(monkeypatch):
    driver = _still_authenticated_driver()
    monkeypatch.setattr(session_reset_module, "get_driver", lambda: driver)

    ok = session_reset_module.logout_and_reset(LOGIN_URL)

    assert ok is False
    # Still landed on the dashboard — nothing confirmed the session actually
    # cleared, which is the whole point: don't just assume the click worked.
    assert driver.current_url == DASHBOARD_URL


def test_logout_and_reset_succeeds_when_login_form_appears(monkeypatch):
    """No regression: when logout genuinely works (app lets the login page
    load, no still-authenticated redirect), confirmation passes."""
    driver = FakeDriver(current_url=DASHBOARD_URL)  # no redirect trap this time
    monkeypatch.setattr(session_reset_module, "get_driver", lambda: driver)

    ok = session_reset_module.logout_and_reset(LOGIN_URL)

    assert ok is True
    assert driver.current_url == LOGIN_URL


def test_logout_and_reset_succeeds_via_two_step_user_menu(monkeypatch):
    """The OrangeHRM-shaped case D8 was actually written for: the logout
    link isn't visible anywhere until a user-menu/avatar trigger is clicked
    first — the direct scan alone must not be the only thing tried."""
    driver = FakeDriver(current_url=DASHBOARD_URL)
    # Nothing matches the direct scan's selectors. A user-menu trigger is
    # registered under one of the generic USER_MENU_HINTS_CSS selectors;
    # clicking it (FakeElement has no click(), so give it one) reveals the
    # logout link the direct scan would then find.
    trigger = FakeElement(displayed=True)
    logout_link = FakeElement(text="Logout", displayed=False)

    def _click_trigger():
        logout_link._displayed = True  # menu opens, link becomes visible

    trigger.click = _click_trigger
    from selenium.webdriver.common.by import By

    driver.register(By.CSS_SELECTOR, "[class*='userdropdown' i]", [trigger])
    # _direct_logout_scan's text-hint pass scans this exact selector string.
    driver.register(
        By.CSS_SELECTOR,
        "a, button, input[type='submit'], input[type='button'], [role='menuitem']",
        [logout_link],
    )
    logout_link.click = lambda: None

    monkeypatch.setattr(session_reset_module, "get_driver", lambda: driver)

    ok = session_reset_module.logout_and_reset(LOGIN_URL)

    assert ok is True
    assert driver.current_url == LOGIN_URL


def test_prepare_fresh_session_fails_when_logout_not_confirmed(monkeypatch):
    driver = _still_authenticated_driver()
    monkeypatch.setattr(session_reset_module, "get_driver", lambda: driver)

    discovery = DiscoveryResult(
        url=LOGIN_URL,
        username="user",
        app_name="App",
        page_title="App",
        discovered_at="t",
        login_url=LOGIN_URL,
        post_login_url=DASHBOARD_URL,
        locators={},
    )

    ok = session_reset_module.prepare_fresh_session(discovery, "pw")

    assert ok is False


def test_run_all_automation_skips_scenario_when_session_reset_fails(monkeypatch):
    """Integration: run_all_automation must not run a scenario's own steps
    against a session it could not confirm was reset — the exact "must not
    let the next scenario start authenticated" requirement. Verified by
    spying on run_scenario: it must never be called."""
    import uts_engine.discovery.automation_runner as runner

    # prepare_fresh_session is imported locally inside run_all_automation
    # (from uts_engine.automation.session_reset import ...), so it is never
    # a module-level attribute on `runner` — patch it at its real source.
    monkeypatch.setattr(session_reset_module, "prepare_fresh_session", lambda *a, **kw: False)

    called = []
    monkeypatch.setattr(runner, "run_scenario", lambda *a, **kw: called.append(1))

    discovery = DiscoveryResult(
        url=LOGIN_URL,
        username="user",
        app_name="App",
        page_title="App",
        discovered_at="t",
        login_url=LOGIN_URL,
        post_login_url=DASHBOARD_URL,
        scenarios=[
            ScenarioDef(
                id="TC_1",
                type="automation",
                title="Some scenario",
                steps=[StepDef(1, "verify", "x", assertion="url_matches", expected="/x")],
                module="Mod",
            )
        ],
    )

    from uts_engine.automation.base import ExecutionLogger

    results = runner.run_all_automation(discovery, "pw", ExecutionLogger("test"))

    assert called == [], "run_scenario must never be called when session reset was not confirmed"
    assert len(results) == 1
    assert results[0].status == "FAIL"
    assert "session reset" in results[0].error.lower() or "confirm" in results[0].error.lower()
