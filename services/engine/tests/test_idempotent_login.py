"""D9: the harness stops logging in (that's session_reset.py's job to log
OUT only now); each scenario's own embedded login steps own authenticating,
and do so idempotently — skip with a real, verified reason when already
authenticated, run for real and confirm when not, FAIL (not SKIP) when they
ran and it still didn't work. This is what the OrangeHRM 0/9 actually traced
to: the harness logged in, then the scenario's own login steps tried to log
in again against an already-authenticated app and found no login form.

No browser required.
"""

from __future__ import annotations

from selenium.webdriver.common.by import By

from tests.fakes import FakeDriver, FakeElement
from uts_engine.automation.base import ExecutionLogger
import uts_engine.discovery.automation_runner as runner
from uts_engine.discovery.discovery import DiscoveryResult, ScenarioDef, StepDef


LOGIN_URL = "https://app.test/login"
DASHBOARD_URL = "https://app.test/dashboard"


def _login_steps() -> list[StepDef]:
    return [
        StepDef(1, "Navigate", "Application URL", LOGIN_URL, expected="loaded"),
        StepDef(2, "SetText", "Username", "u", locator_by="id", locator_value="username"),
        StepDef(3, "SetPassword", "Password", "p", locator_by="id", locator_value="password"),
        StepDef(4, "PerformClick", "Login", "", locator_by="id", locator_value="login-btn"),
    ]


def _discovery(**overrides) -> DiscoveryResult:
    kwargs = dict(
        url=LOGIN_URL,
        username="u",
        app_name="App",
        page_title="App",
        discovered_at="t",
        login_url=LOGIN_URL,
        post_login_url=DASHBOARD_URL,
        locators={"username": {"by": "id", "value": "username"}},
    )
    kwargs.update(overrides)
    return DiscoveryResult(**kwargs)


def test_credentialed_scenario_logs_in_once_when_not_authenticated(monkeypatch):
    """Not authenticated at start: the embedded login steps run for real
    (once — verified by asserting their messages are real interaction
    messages, not the synthetic "already authenticated" one), a
    confirmation Verify is appended, and the rest of the scenario proceeds
    once confirmed."""
    driver = FakeDriver(current_url=LOGIN_URL)
    monkeypatch.setattr(runner, "get_driver", lambda: driver)
    driver.register(By.ID, "username", [FakeElement(displayed=True)])
    driver.register(By.ID, "password", [FakeElement(displayed=True)])
    login_btn = FakeElement(displayed=True)
    login_btn.click = lambda: setattr(driver, "current_url", DASHBOARD_URL)
    driver.register(By.ID, "login-btn", [login_btn])

    rest_step = StepDef(5, "Verify", "Dashboard", "", assertion="url_matches", expected=DASHBOARD_URL)
    scenario = ScenarioDef(
        id="TC_1", type="automation", title="Test", steps=[*_login_steps(), rest_step], module="Mod"
    )

    result = runner.run_scenario(scenario, _discovery(), "p", ExecutionLogger("test"))

    login_results = result.steps[:4]
    for r in login_results:
        assert "Already authenticated" not in r.message, "login steps should have run for real, not been skipped"
    confirm_steps = [s for s in result.steps if s.object_name == "Authenticated"]
    assert len(confirm_steps) == 1, "exactly one confirmation check, not one per attempt"
    assert confirm_steps[0].status == "PASS"
    assert result.status == "PASS"


def test_login_failure_reports_fail_not_skip(monkeypatch):
    """Ran the login steps, but confirmation never succeeds (no dashboard
    redirect simulated) -> the scenario is FAIL, not SKIP, and names what
    was checked."""
    driver = FakeDriver(current_url=LOGIN_URL)  # never moves off the login page
    monkeypatch.setattr(runner, "get_driver", lambda: driver)
    driver.register(By.ID, "username", [FakeElement(displayed=True)])
    driver.register(By.ID, "password", [FakeElement(displayed=True)])
    driver.register(By.ID, "login-btn", [FakeElement(displayed=True)])  # click does nothing

    scenario = ScenarioDef(id="TC_2", type="automation", title="Test", steps=_login_steps(), module="Mod")

    result = runner.run_scenario(scenario, _discovery(), "p", ExecutionLogger("test"))

    assert result.status == "FAIL"
    assert result.status != "SKIP"
    confirm_steps = [s for s in result.steps if s.object_name == "Authenticated"]
    assert len(confirm_steps) == 1
    assert confirm_steps[0].status == "FAIL"
    assert "could not be confirmed" in confirm_steps[0].message.lower()


def test_already_authenticated_scenario_skips_login_with_real_reason(monkeypatch):
    """Interactive-session-shaped case: the app is already on the
    post-login URL when the scenario starts. Login steps are marked
    satisfied with a message naming what was checked — not run, not a
    blind/silent pass."""
    driver = FakeDriver(current_url=DASHBOARD_URL)  # already authenticated
    monkeypatch.setattr(runner, "get_driver", lambda: driver)
    # No username/login-btn registered at all — if the code tried to run
    # the login steps for real, they would fail with "not found".

    rest_step = StepDef(5, "Verify", "Dashboard", "", assertion="url_matches", expected=DASHBOARD_URL)
    scenario = ScenarioDef(
        id="TC_3", type="automation", title="Test", steps=[*_login_steps(), rest_step], module="Mod"
    )

    result = runner.run_scenario(scenario, _discovery(), "p", ExecutionLogger("test"))

    login_results = result.steps[:4]
    for r in login_results:
        assert r.status == "PASS"
        assert "Already authenticated" in r.message
    assert result.status == "PASS"


def test_check_auth_state_falls_back_to_element_visible_for_single_page_apps(monkeypatch):
    """Real bug caught live against the bundled demo fixture: when
    post_login_url equals login_url (a single-page app — every screen is
    the same URL), trusting url_matches(post_login_url) reports
    "authenticated" unconditionally, including immediately after a
    verified logout. It must fall back to checking the username field's
    visibility instead, which does discriminate for such an app."""
    driver = FakeDriver(current_url=LOGIN_URL)
    monkeypatch.setattr(runner, "get_driver", lambda: driver)
    discovery = _discovery(login_url=LOGIN_URL, post_login_url=LOGIN_URL)  # SPA: identical URLs

    # Username field visible -> genuinely on the login page -> not authenticated.
    driver.register(By.ID, "username", [FakeElement(displayed=True)])
    authenticated, detail = runner._check_auth_state(discovery)
    assert authenticated is False, detail

    # Username field hidden (dashboard active instead) -> authenticated,
    # even though the URL never changed.
    driver.register(By.ID, "username", [FakeElement(displayed=False)])
    authenticated2, detail2 = runner._check_auth_state(discovery)
    assert authenticated2 is True, detail2


def test_run_all_automation_never_calls_login_between_scenarios(monkeypatch):
    """Integration: run_all_automation's harness-level session reset must
    never call a login function — only logout_and_reset. Spied by patching
    perform_login_from_discovery/perform_login_from_locators to fail the
    test if called."""
    import uts_engine.automation.session_reset as session_reset_module

    def _fail_if_called(*a, **kw):
        raise AssertionError("harness must not log in — that's the scenario's own job now (D9)")

    monkeypatch.setattr(session_reset_module, "perform_login_from_discovery", _fail_if_called)
    monkeypatch.setattr(session_reset_module, "perform_login_from_locators", _fail_if_called)

    driver = FakeDriver(current_url=LOGIN_URL)
    monkeypatch.setattr(runner, "get_driver", lambda: driver)
    monkeypatch.setattr(session_reset_module, "get_driver", lambda: driver)
    # Nothing registered for username/password/login-btn -> login steps
    # will FAIL for real, which is fine — this test only cares that the
    # harness itself never calls a login function.

    scenario = ScenarioDef(id="TC_4", type="automation", title="Test", steps=_login_steps(), module="Mod")
    discovery = _discovery(scenarios=[scenario])

    logger = ExecutionLogger("test")
    results = runner.run_all_automation(discovery, "p", logger, run_modules_only=["Mod"])

    assert len(results) == 1  # ran (and failed, harmlessly) rather than raising


def test_interactive_session_never_logs_out_between_scenarios(monkeypatch):
    """has_session() True (customer-supplied session, no credentials) ->
    safe_logout_after_each() gates logout_after_each to False upstream of
    run_all_automation, so it must never call logout_and_reset here either."""
    import uts_engine.automation.selenium_session as selenium_session
    import uts_engine.automation.session_reset as session_reset_module

    monkeypatch.setattr(selenium_session, "has_session", lambda: True)

    def _fail_if_called(*a, **kw):
        raise AssertionError("must not log out an interactive session with no credentials to sign back in with")

    monkeypatch.setattr(session_reset_module, "logout_and_reset", _fail_if_called)

    driver = FakeDriver(current_url=DASHBOARD_URL)
    monkeypatch.setattr(runner, "get_driver", lambda: driver)

    rest_step = StepDef(5, "Verify", "Dashboard", "", assertion="url_matches", expected=DASHBOARD_URL)
    scenario = ScenarioDef(
        id="TC_5", type="automation", title="Test", steps=[*_login_steps(), rest_step], module="Mod"
    )
    discovery = _discovery(scenarios=[scenario])

    logger = ExecutionLogger("test")
    # logout_after_each mirrors what the real caller (cli.py/host.py/
    # worker/agent.py) computes via safe_logout_after_each(...) — False
    # here because has_session() is True.
    results = runner.run_all_automation(
        discovery, "p", logger, logout_after_each=False, run_modules_only=["Mod"]
    )

    assert len(results) == 1
    assert results[0].status == "PASS"
    login_results = results[0].steps[:4]
    for r in login_results:
        assert "Already authenticated" in r.message
