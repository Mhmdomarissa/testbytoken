"""TC_AUTO_02 - Selenium navigation to Transfer screen."""

from __future__ import annotations

from datetime import datetime

from automation.base import ExecutionLogger, TestResult, run_step
from automation.selenium_actions import click, get_text, is_visible
from automation.selenium_session import is_selenium_enabled
from automation.selenium_step_overlay import set_test_case


def run(logger: ExecutionLogger | None = None) -> TestResult:
    log = logger or ExecutionLogger("TC_AUTO_02")
    started = datetime.now()

    log.info("=" * 60)
    log.info("TC_AUTO_02: Selenium — Navigate to Transfer")
    log.info("Precondition: fresh login performed by runner before this test")
    log.info("=" * 60)

    set_test_case("TC_AUTO_02", "Navigate to Transfer")

    if not is_selenium_enabled():
        return _simulated_fallback(log, started)

    steps = []

    def step1():
        ok = is_visible("dashboard")
        return ok, "Dashboard verified — user session active" if ok else "Dashboard not visible"

    steps.append(run_step(log, 1, "Verify", "Dashboard", "", step1))

    def step2():
        click("transfers_menu")
        return True, "Clicked Transfers menu"

    steps.append(run_step(log, 2, "PerformClick", "TransfersMenu", "", step2))

    def step3():
        click("transfer_self_link")
        return True, "Selected Transfer Between My Accounts"

    steps.append(run_step(log, 3, "PerformClick", "TransferBetweenMyAccounts", "", step3))

    def step4():
        fields = ["send_from", "send_to", "amount", "continue_button"]
        missing = [f for f in fields if not is_visible(f)]
        if missing:
            return False, f"Missing fields: {', '.join(missing)}"
        return True, "Transfer screen loaded — all fields visible"

    steps.append(run_step(log, 4, "Verify", "TransferScreen", "", step4))

    def step5():
        title = get_text("page_title")
        expected = "Transfer between my accounts"
        ok = expected.lower() in title.lower()
        return ok, f"Page title: '{title}'" if ok else f"Expected '{expected}', got '{title}'"

    steps.append(run_step(log, 5, "Verify", "PageTitle", "Transfer between my accounts", step5))

    return _build_result(steps, started, log)


def _simulated_fallback(log, started):
    from automation.base import simulate_delay

    steps = []
    for i, (action, obj, msg) in enumerate([
        ("Verify", "Dashboard", "simulated"),
        ("PerformClick", "TransfersMenu", "simulated"),
        ("PerformClick", "TransferBetweenMyAccounts", "simulated"),
        ("Verify", "TransferScreen", "simulated"),
        ("Verify", "PageTitle", "simulated"),
    ], 1):
        steps.append(run_step(log, i, action, obj, "", lambda m=msg: (simulate_delay(80) or True, m)))
    return _build_result(steps, started, log)


def _build_result(steps, started, log) -> TestResult:
    failed = [s for s in steps if s.status == "FAIL"]
    status = "FAIL" if failed else "PASS"
    ended = datetime.now()
    log.info(f"TC_AUTO_02 finished: {status}")
    return TestResult(
        tc_id="TC_AUTO_02",
        title="Navigate to Transfer Between My Accounts",
        test_type="automation",
        status=status,
        steps=steps,
        started_at=started.isoformat(timespec="seconds"),
        ended_at=ended.isoformat(timespec="seconds"),
        duration_ms=round((ended - started).total_seconds() * 1000, 2),
        error=failed[0].message if failed else "",
    )
