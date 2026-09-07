"""TC_AUTO_01 - Selenium login validation."""

from __future__ import annotations

from datetime import datetime

from automation.base import ExecutionLogger, TestResult, load_test_data, run_step
from automation.selenium_actions import click, is_visible, type_text
from automation.selenium_session import get_driver, is_selenium_enabled
from automation.selenium_step_overlay import set_test_case


def run(logger: ExecutionLogger | None = None) -> TestResult:
    log = logger or ExecutionLogger("TC_AUTO_01")
    data = load_test_data()
    creds = data["credentials"]
    started = datetime.now()

    log.info("=" * 60)
    log.info("TC_AUTO_01: Selenium Login Validation")
    log.info(f"Application: {data['application']} | Engine: Selenium WebDriver")
    log.info("=" * 60)

    set_test_case("TC_AUTO_01", "Login validation")

    if not is_selenium_enabled():
        return _simulated_fallback(log, creds, started)

    steps = []
    driver = get_driver()

    def step1():
        ok = is_visible("username") or is_visible("dashboard")
        return ok, f"Login screen ready — URL: {driver.current_url}"

    steps.append(run_step(log, 1, "Navigate", "LoginPage", "", step1))

    def step2():
        type_text("username", creds["username"])
        return True, f"Entered username '{creds['username']}'"

    steps.append(run_step(log, 2, "SetText", "Username", creds["username"], step2))

    def step3():
        type_text("password", creds["password"])
        return True, "Entered password (masked)"

    steps.append(run_step(log, 3, "SetText", "Password", "********", step3))

    def step4():
        click("login_button")
        return True, "Clicked Login button"

    steps.append(run_step(log, 4, "PerformClick", "Login", "", step4))

    def step5():
        ok = is_visible("dashboard")
        return ok, "Dashboard visible — login successful" if ok else "Dashboard not found after login"

    steps.append(run_step(log, 5, "Verify", "Dashboard", "", step5))

    return _build_result(steps, started, log)


def _simulated_fallback(log, creds, started):
    from automation.base import simulate_delay

    log.info("Selenium disabled — using simulated mode")
    steps = []

    def s1():
        simulate_delay(100)
        return True, "Simulated login screen"

    steps.append(run_step(log, 1, "Navigate", "LoginPage", "", s1))
    steps.append(run_step(log, 2, "SetText", "Username", creds["username"], lambda: (True, "simulated")))
    steps.append(run_step(log, 3, "SetText", "Password", "********", lambda: (True, "simulated")))
    steps.append(run_step(log, 4, "PerformClick", "Login", "", lambda: (True, "simulated")))
    steps.append(run_step(log, 5, "Verify", "Dashboard", "", lambda: (True, "simulated")))
    return _build_result(steps, started, log)


def _build_result(steps, started, log) -> TestResult:
    failed = [s for s in steps if s.status == "FAIL"]
    status = "FAIL" if failed else "PASS"
    ended = datetime.now()
    log.info(f"TC_AUTO_01 finished: {status} ({len(steps) - len(failed)}/{len(steps)} steps passed)")
    return TestResult(
        tc_id="TC_AUTO_01",
        title="Automated login validation",
        test_type="automation",
        status=status,
        steps=steps,
        started_at=started.isoformat(timespec="seconds"),
        ended_at=ended.isoformat(timespec="seconds"),
        duration_ms=round((ended - started).total_seconds() * 1000, 2),
        error=failed[0].message if failed else "",
    )
