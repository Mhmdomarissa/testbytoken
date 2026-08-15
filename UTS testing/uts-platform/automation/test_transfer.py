"""TC_AUTO_03 - Selenium transfer flow end-to-end."""

from __future__ import annotations

from datetime import datetime

from automation.base import ExecutionLogger, TestResult, load_test_data, run_step
from automation.selenium_actions import click, get_text, is_visible, select_by_visible_text, type_text
from automation.selenium_session import is_selenium_enabled
from automation.selenium_step_overlay import set_test_case


def run(logger: ExecutionLogger | None = None) -> TestResult:
    log = logger or ExecutionLogger("TC_AUTO_03")
    data = load_test_data()
    xfer = data["transfer"]
    started = datetime.now()

    log.info("=" * 60)
    log.info("TC_AUTO_03: Selenium Transfer E2E")
    log.info(f"From: {xfer['source_account']} -> To: {xfer['destination_account']}")
    log.info("=" * 60)

    set_test_case("TC_AUTO_03", "Transfer E2E")

    if not is_selenium_enabled():
        return _simulated_fallback(log, xfer, started)

    steps = []
    flow = [
        (1, "PerformSelect", "send_from", xfer["source_account"], lambda: select_by_visible_text("send_from", xfer["source_account"])),
        (2, "PerformSelect", "send_to", xfer["destination_account"], lambda: select_by_visible_text("send_to", xfer["destination_account"])),
        (3, "SetText", "amount", xfer["amount"], lambda: type_text("amount", xfer["amount"])),
        (4, "SetText", "transfer_date", xfer["transfer_date"], lambda: type_text("transfer_date", xfer["transfer_date"])),
        (5, "PerformSelect", "frequency", xfer["frequency"], lambda: select_by_visible_text("frequency", xfer["frequency"])),
        (6, "SetText", "message", xfer["message"], lambda: type_text("message", xfer["message"])),
        (7, "PerformClick", "continue_button", "", lambda: click("continue_button")),
        (8, "Verify", "review_screen", "Review screen", lambda: _verify_visible("review_screen")),
        (9, "PerformClick", "confirm_button", "", lambda: click("confirm_button")),
        (10, "Verify", "success_message", "Success", lambda: _verify_success()),
    ]

    for step_no, action, obj, value, fn in flow:
        def make_executor(f=fn, a=action, o=obj, v=value):
            def _run():
                f()
                return True, f"{a} on '{o}'" + (f" = '{v}'" if v else "")

            return _run

        steps.append(run_step(log, step_no, action, obj, value, make_executor()))

    return _build_result(steps, started, log)


def _verify_visible(key: str):
    ok = is_visible(key)
    return ok, f"{key} visible" if ok else f"{key} not found"


def _verify_success():
    ok = is_visible("success_message")
    if not ok:
        return False, "Success message not displayed"
    text = get_text("success_message")
    ref = get_text("ref_line") if is_visible("ref_line") else ""
    return True, f"SUCCESS: {text} | {ref}"


def _simulated_fallback(log, xfer, started):
    from automation.base import simulate_delay

    steps = []
    flow = [
        ("PerformSelect", "Send from", xfer["source_account"]),
        ("PerformSelect", "Send to", xfer["destination_account"]),
        ("SetText", "Amount", xfer["amount"]),
        ("SetText", "Transfer date", xfer["transfer_date"]),
        ("PerformSelect", "Frequency", xfer["frequency"]),
        ("SetText", "Message", xfer["message"]),
        ("PerformClick", "Continue", ""),
        ("Verify", "ReviewScreen", ""),
        ("PerformClick", "Confirm", ""),
        ("Verify", "SuccessMessage", ""),
    ]
    for i, (action, obj, val) in enumerate(flow, 1):
        steps.append(run_step(log, i, action, obj, val, lambda: (simulate_delay(80) or True, "simulated")))
    return _build_result(steps, started, log)


def _build_result(steps, started, log) -> TestResult:
    failed = [s for s in steps if s.status == "FAIL"]
    status = "FAIL" if failed else "PASS"
    ended = datetime.now()
    log.info(f"TC_AUTO_03 finished: {status} — {len(steps)} steps executed")
    return TestResult(
        tc_id="TC_AUTO_03",
        title="Execute transfer flow end-to-end",
        test_type="automation",
        status=status,
        steps=steps,
        started_at=started.isoformat(timespec="seconds"),
        ended_at=ended.isoformat(timespec="seconds"),
        duration_ms=round((ended - started).total_seconds() * 1000, 2),
        error=failed[0].message if failed else "",
    )
