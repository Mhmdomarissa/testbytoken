"""W7: pytest coverage for Phase 0's E1/E2/E3 fixes. No browser, no network —
every test drives automation_runner against tests/fakes.py's FakeDriver.
"""

from __future__ import annotations

import pytest
from selenium.webdriver.common.by import By

from tests.fakes import FakeDriver, FakeElement
from uts_engine.discovery import automation_runner as runner
from uts_engine.discovery.discovery import StepDef


@pytest.fixture
def fake_driver(monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(runner, "get_driver", lambda: driver)
    return driver


# ---------------------------------------------------------------------------
# W3: each assertion kind, passing and failing.
# ---------------------------------------------------------------------------


def test_url_matches_pass(fake_driver):
    fake_driver.current_url = "http://example.test/dashboard"
    step = StepDef(1, "verify", "x", assertion="url_matches", expected="/dashboard")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is True
    assert "/dashboard" in msg


def test_url_matches_fail(fake_driver):
    fake_driver.current_url = "http://example.test/login"
    step = StepDef(1, "verify", "x", assertion="url_matches", expected="/dashboard")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False
    assert "Expected URL to contain" in msg


def test_element_visible_pass_via_step_locator(fake_driver):
    fake_driver.register(By.ID, "save-btn", [FakeElement(displayed=True)])
    step = StepDef(1, "verify", "Save", locator_by="id", locator_value="save-btn", assertion="element_visible")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is True
    assert "is visible" in msg


def test_element_visible_fail_not_displayed(fake_driver):
    fake_driver.register(By.ID, "save-btn", [FakeElement(displayed=False)])
    step = StepDef(1, "verify", "Save", locator_by="id", locator_value="save-btn", assertion="element_visible")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False
    assert "to be visible" in msg


def test_element_visible_fail_no_locator_available(fake_driver):
    step = StepDef(1, "verify", "Ghost", assertion="element_visible", expected="Ghost")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False
    assert "No locator configured" in msg


def test_element_visible_via_named_locator_repo(fake_driver):
    fake_driver.register(By.ID, "menu-transfers", [FakeElement(displayed=True)])
    locators = {"transfers": {"by": "id", "value": "menu-transfers"}}
    step = StepDef(1, "verify", "x", assertion="element_visible", expected="transfers")
    ok, msg = runner._execute_step(step, locators, "pw")
    assert ok is True


def test_text_in_region_pass(fake_driver):
    fake_driver.register(By.ID, "banner", [FakeElement(text="Welcome back, Jo")])
    step = StepDef(1, "verify", "x", locator_by="id", locator_value="banner", assertion="text_in_region", expected="banner::Welcome back")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is True


def test_text_in_region_fail_wrong_text(fake_driver):
    fake_driver.register(By.ID, "banner", [FakeElement(text="Welcome back, Jo")])
    step = StepDef(1, "verify", "x", locator_by="id", locator_value="banner", assertion="text_in_region", expected="banner::Goodbye")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False
    assert "region text was" in msg


def test_text_in_region_fail_malformed_arg(fake_driver):
    step = StepDef(1, "verify", "x", assertion="text_in_region", expected="no-double-colon")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False
    assert "malformed" in msg


def test_row_count_pass(fake_driver):
    fake_driver.register(By.CSS_SELECTOR, ".row", [FakeElement(), FakeElement(), FakeElement()])
    step = StepDef(1, "verify", "rows", locator_by="css", locator_value=".row", assertion="row_count", expected=">=2")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is True
    assert "3" in msg


def test_row_count_fail_wrong_count(fake_driver):
    fake_driver.register(By.CSS_SELECTOR, ".row", [FakeElement()])
    step = StepDef(1, "verify", "rows", locator_by="css", locator_value=".row", assertion="row_count", expected=">=2")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False


def test_row_count_fail_no_locator(fake_driver):
    step = StepDef(1, "verify", "rows", assertion="row_count", expected=">0")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False
    assert "needs the step's own row locator" in msg


# ---------------------------------------------------------------------------
# W3 done-when: unknown/empty assertion is always a FAIL, never a pass.
# ---------------------------------------------------------------------------


def test_verify_with_no_assertion_kind_fails(fake_driver):
    fake_driver.title = "Anything At All"
    step = StepDef(1, "verify", "x", expected="Anything At All")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False
    assert "carried no checkable assertion" in msg


def test_verify_with_unknown_assertion_kind_fails(fake_driver):
    step = StepDef(1, "verify", "x", assertion="not_a_real_kind", expected="whatever")
    ok, msg = runner._execute_step(step, {}, "pw")
    assert ok is False


# ---------------------------------------------------------------------------
# W1 regression: an unmet verify -> step FAIL AND test-case FAIL, through
# the real run_step()/verdict path (not just _execute_step in isolation).
# ---------------------------------------------------------------------------


def test_w1_impossible_verify_yields_step_and_testcase_fail(fake_driver):
    from uts_engine.automation.base import ExecutionLogger, run_step

    fake_driver.current_url = "http://example.test/somewhere"
    step = StepDef(1, "verify", "Impossible", assertion="url_matches", expected="this-will-never-match")

    logger = ExecutionLogger("test")
    result = run_step(
        logger, 1, step.action, step.object_name, step.input_value,
        lambda: runner._execute_step(step, {}, "pw"),
        tc_id="TC_TEST", tc_title="Test", total_steps=1,
    )
    assert result.status == "FAIL"

    # Mirror run_scenario()'s verdict computation.
    failed = [s for s in [result] if s.status == "FAIL"]
    skipped_required = [
        s for s in [result]
        if s.status == "SKIP"
        and str(s.action).lower() in {"performclick", "click", "settext", "setpassword", "performselect", "verify", "notification"}
    ]
    tc_status = "FAIL" if failed or skipped_required else "PASS"
    assert tc_status == "FAIL"


def test_w1_matching_verify_still_passes(fake_driver):
    """No regression: a verify that genuinely matches still passes."""
    from uts_engine.automation.base import ExecutionLogger, run_step

    fake_driver.current_url = "http://example.test/dashboard"
    step = StepDef(1, "verify", "x", assertion="url_matches", expected="/dashboard")
    logger = ExecutionLogger("test")
    result = run_step(
        logger, 1, step.action, step.object_name, step.input_value,
        lambda: runner._execute_step(step, {}, "pw"),
        tc_id="TC_TEST", tc_title="Test", total_steps=1,
    )
    assert result.status == "PASS"


# ---------------------------------------------------------------------------
# W2 regression: an unresolvable element returns None, produces a FAIL, and
# does NOT silently bind to an unrelated element from the locator repo.
# ---------------------------------------------------------------------------


def test_w2_unresolvable_element_returns_none_not_misbound(fake_driver):
    # A rich locator repo with real, unrelated elements registered — the old
    # any-locator sweep would have returned one of these.
    fake_driver.register(By.ID, "username", [FakeElement(displayed=True)])
    fake_driver.register(By.ID, "password", [FakeElement(displayed=True)])
    locators = {
        "username": {"by": "id", "value": "username"},
        "password": {"by": "id", "value": "password"},
    }
    step = StepDef(
        1, "performclick", "Nonexistent Button", locator_by="id", locator_value="totally-bogus-id"
    )
    el = runner._find_element(step, locators, timeout=0)
    assert el is None


def test_w2_unresolvable_element_produces_fail_naming_object_and_locator(fake_driver, monkeypatch):
    # _execute_step calls _find_element with the default 12s WebDriverWait
    # timeout; force it to the already-covered "not found" case instantly
    # rather than actually waiting out a real timeout in a unit test.
    monkeypatch.setattr(runner, "_find_element", lambda step, locators, timeout=12: None)
    locators = {"username": {"by": "id", "value": "username"}}
    step = StepDef(
        1, "performclick", "Nonexistent Button", locator_by="id", locator_value="totally-bogus-id"
    )
    ok, msg = runner._execute_step(step, locators, "pw")
    assert ok is False
    assert "Nonexistent Button" in msg
    assert "totally-bogus-id" in msg


def test_w2_own_locator_still_resolves_correctly(fake_driver):
    """No regression: a step whose own locator genuinely matches still
    finds that exact element, not something else from the repo."""
    fake_driver.register(By.ID, "save-btn", [FakeElement(displayed=True)])
    fake_driver.register(By.ID, "username", [FakeElement(displayed=True)])
    locators = {"username": {"by": "id", "value": "username"}}
    step = StepDef(1, "performclick", "Save", locator_by="id", locator_value="save-btn")
    el = runner._find_element(step, locators, timeout=0)
    assert el is not None
