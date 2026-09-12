"""Execute dynamically discovered automation scenarios."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from uts_engine.automation.base import ExecutionLogger, TestResult, run_step
from uts_engine.automation.selenium_session import get_driver, navigate
from uts_engine.automation.selenium_step_overlay import register_step_locator, set_dynamic_locators, set_test_case
from uts_engine.discovery.common_actions import execute_workflow_action, infer_action_from_button, normalize_action, save_actions_catalog
from uts_engine.discovery.discovery import AUTOMATION_TYPES, DiscoveryResult, ScenarioDef, StepDef
from uts_engine.discovery.login_helpers import fill_username_and_trigger_role, wait_role_select_enabled
from uts_engine.workdir import data_root

BY_MAP = {
    "id": By.ID,
    "name": By.NAME,
    "css": By.CSS_SELECTOR,
    "xpath": By.XPATH,
    "class": By.CLASS_NAME,
}

GENERATED_DIR = data_root() / "generated"


def save_discovery(discovery: DiscoveryResult) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / "discovered-flow.json"
    path.write_text(json.dumps(discovery.to_dict(), indent=2), encoding="utf-8")
    return path


def load_discovery() -> DiscoveryResult:
    data = json.loads((GENERATED_DIR / "discovered-flow.json").read_text(encoding="utf-8"))
    scenarios = []
    for s in data["scenarios"]:
        steps = [StepDef(**st) for st in s["steps"]]
        scenarios.append(
            ScenarioDef(
                s["id"],
                s["type"],
                s["title"],
                steps,
                module=s.get("module", ""),
            )
        )
    return DiscoveryResult(
        url=data["url"],
        username=data["username"],
        app_name=data["app_name"],
        page_title=data["page_title"],
        discovered_at=data["discovered_at"],
        login_url=data["login_url"],
        post_login_url=data["post_login_url"],
        scenarios=scenarios,
        locators=data.get("locators", {}),
        modules=list(data.get("modules") or []),
    )


def _dismiss_overlays(driver) -> None:
    """Best-effort close cookie / consent banners that block clicks."""
    labels = (
        "Accept All",
        "Accept all",
        "Accept",
        "Agree",
        "I agree",
        "Got it",
        "Allow all",
        "Close",
    )
    for label in labels:
        try:
            els = driver.find_elements(
                By.XPATH,
                f"//button[contains(normalize-space(.),'{label}')] "
                f"| //a[contains(normalize-space(.),'{label}')] "
                f"| //*[@role='button'][contains(normalize-space(.),'{label}')]",
            )
            for el in els:
                if el.is_displayed() and el.is_enabled():
                    try:
                        el.click()
                    except Exception:  # noqa: BLE001
                        driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.35)
                    return
        except Exception:  # noqa: BLE001
            continue


def _text_candidates(label: str) -> list[str]:
    text = (label or "").strip()
    if not text:
        return []
    parts = [p for p in text.split() if p]
    out = [text]
    if len(parts) >= 2:
        out.append(parts[0])
        out.append(" ".join(parts[:2]))
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(item)
    return uniq


def _find_element(step: StepDef, locators: dict[str, dict[str, str]], timeout: int = 12):
    """Find element for a step. Returns None instead of raising when not found."""
    driver = get_driver()
    _dismiss_overlays(driver)

    def _visible(el):
        try:
            return el is not None and el.is_displayed()
        except Exception:  # noqa: BLE001
            return False

    if step.locator_by and step.locator_value:
        by = BY_MAP.get(step.locator_by, By.ID)
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, step.locator_value))
            )
            if _visible(el):
                return el
        except Exception:  # noqa: BLE001
            pass
        try:
            matches = [e for e in driver.find_elements(by, step.locator_value) if _visible(e)]
            if matches:
                return matches[0]
            # Prefer any match even if not displayed (mega-menus / off-canvas)
            matches = driver.find_elements(by, step.locator_value)
            if matches:
                return matches[0]
        except Exception:  # noqa: BLE001
            pass
        if step.locator_by == "id" and step.locator_value:
            try:
                el = driver.find_element(By.CSS_SELECTOR, f"[id*='{step.locator_value}']")
                if _visible(el):
                    return el
            except Exception:  # noqa: BLE001
                pass

    # Fallback: find by visible text / partial link (marketing sites, menus)
    for label in _text_candidates(step.object_name):
        safe = label.replace("'", "")
        xpaths = [
            f"//a[contains(normalize-space(.),'{safe}')]",
            f"//button[contains(normalize-space(.),'{safe}')]",
            f"//*[@role='link' or @role='menuitem' or @role='button'][contains(normalize-space(.),'{safe}')]",
            f"//nav//*[contains(normalize-space(.),'{safe}')]",
            f"//header//*[contains(normalize-space(.),'{safe}')]",
        ]
        for xp in xpaths:
            try:
                matches = [e for e in driver.find_elements(By.XPATH, xp) if _visible(e)]
                if matches:
                    return matches[0]
                matches = driver.find_elements(By.XPATH, xp)
                if matches:
                    return matches[0]
            except Exception:  # noqa: BLE001
                continue
        try:
            el = driver.find_element(By.PARTIAL_LINK_TEXT, label)
            if el:
                return el
        except Exception:  # noqa: BLE001
            pass

    for loc in locators.values():
        if not isinstance(loc, dict):
            continue
        by = BY_MAP.get(loc.get("by", ""), By.ID)
        try:
            el = driver.find_element(by, loc["value"])
            if _visible(el):
                return el
        except Exception:  # noqa: BLE001
            continue
    return None


def _is_critical_step(step: StepDef) -> bool:
    """Login/navigation/explicit clicks must not be silently skipped as PASS."""
    action = step.action.lower()
    obj = step.object_name.lower()
    if action == "navigate":
        return True
    # A verify/notification that finds nothing checked nothing — it must be
    # able to FAIL the test case, not quietly SKIP into a PASS (E1).
    if action in {"verify", "notification"}:
        return True
    if any(h in obj for h in ("password", "username", "user name", "login", "sign in", "signin")):
        return True
    if action == "performselect" and obj == "role":
        return True
    # Explicit UI clicks with locators (AI link/module navigation) are required
    if action in {"performclick", "click"} and step.locator_by and step.locator_value:
        return True
    if action in {"performclick", "click"} and obj and "page" not in obj:
        return True
    return False


def _skip_or_fail(step: StepDef, reason: str) -> tuple[bool, str]:
    if _is_critical_step(step):
        return False, reason
    return True, f"SKIP: {reason}"


def _execute_step(
    step: StepDef,
    locators: dict,
    password: str,
    context: dict | None = None,
) -> tuple[bool, str]:
    driver = get_driver()
    action = normalize_action(step.action)
    ctx = context if context is not None else {}

    wf_ok, wf_msg, is_ui = execute_workflow_action(
        action,
        step.object_name,
        step.input_value,
        step.expected,
        ctx,
    )
    if not is_ui:
        ctx["_last_message"] = wf_msg
        return wf_ok, wf_msg

    action = action.lower()

    try:
        if action == "navigate":
            navigate(driver, step.input_value or step.object_name)
            return True, f"Opened {driver.current_url}"

        if action == "verify":
            obj_lower = step.object_name.lower()
            if obj_lower in ("post-login page", "logged-in page", "dashboard"):
                left_login = driver.execute_script(
                    "var e=document.getElementById('screen-login');"
                    "return !e || !e.classList.contains('active');"
                )
                if left_login:
                    return True, "Login successful — left login screen"
                try:
                    pwd = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                    if not pwd.is_displayed():
                        return True, "Login successful — password field hidden"
                except Exception:  # noqa: BLE001
                    return True, "Login successful — no password field"
                login_url = locators.get("_login_url", "")
                if login_url and driver.current_url != login_url:
                    return True, f"URL changed to {driver.current_url}"
                return _skip_or_fail(
                    step,
                    "Expected to have left the login screen after signing in "
                    f"(no password field, or a URL change from {login_url or '(unknown login url)'}); "
                    f"still on {driver.current_url}",
                )

            if "search result" in obj_lower:
                rows = driver.find_elements(By.CSS_SELECTOR, ".oxd-table-body .oxd-table-row, table tbody tr")
                if rows:
                    return True, f"Search results visible ({len(rows)} row(s))"
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                if "no records" in page_text or "no data" in page_text:
                    return True, "Search completed — no records found"
                return _skip_or_fail(
                    step,
                    "Expected result rows (.oxd-table-body .oxd-table-row / table tbody tr) or a "
                    "'no records'/'no data' message; page body contained neither",
                )

            if "module complete" in obj_lower or "functional flow completed" in (step.expected or "").lower():
                module_hint = (step.input_value or step.object_name or "").lower()
                url = driver.current_url.lower()
                body = driver.find_element(By.TAG_NAME, "body").text.lower()
                if module_hint and module_hint in url:
                    return True, f"Module '{step.input_value}' page active"
                if module_hint and module_hint in body:
                    return True, f"Module '{step.input_value}' content visible"
                toasts = driver.find_elements(By.CSS_SELECTOR, ".oxd-toast, [role='alert']")
                toast_text = " ".join((t.text or "") for t in toasts).lower()
                if any(w in toast_text for w in ("success", "saved", "updated", "created")):
                    return True, "Success notification shown"
                return _skip_or_fail(
                    step,
                    f"Expected '{module_hint or '(no module hint)'}' in the URL or page body, or a "
                    f"success/saved/updated/created toast; found none of those on {driver.current_url}",
                )

            if step.input_value and step.input_value.startswith("http"):
                return True, f"Current URL: {driver.current_url}"
            headings = driver.find_elements(By.CSS_SELECTOR, "h1, h2, h6, .oxd-topbar-header-breadcrumb")
            page_text = driver.title + " " + " ".join(h.text for h in headings if h.text)
            expected = step.input_value or step.expected or step.object_name
            if expected.lower() in page_text.lower():
                return True, f"Verified '{expected}'"
            # Soft verify for module pages: match URL/body tokens (e.g. About PMI)
            hint = expected.replace(" Page", "").replace(" page", "").strip().lower()
            url = driver.current_url.lower()
            body = driver.find_element(By.TAG_NAME, "body").text.lower()
            tokens = [t for t in hint.split() if len(t) > 2]
            if tokens and all(t in url or t in body or t in page_text.lower() for t in tokens[:2]):
                return True, f"Verified page context for '{expected}'"
            if any(t in url for t in tokens):
                return True, f"URL indicates '{expected}': {driver.current_url}"
            return _skip_or_fail(
                step,
                f"Expected '{expected}' in the page title/headings/URL/body; "
                f"found title+headings=\"{page_text.strip()[:120]}\", url={driver.current_url}",
            )

        if action == "notification":
            toast_selectors = ".oxd-toast, .oxd-toast-content, [role='alert'], .toast"
            toasts = driver.find_elements(By.CSS_SELECTOR, toast_selectors)
            toast_text = " ".join((t.text or "") for t in toasts if t.is_displayed())
            expected = (step.input_value or step.expected or step.object_name or "success").lower()
            combined = (toast_text + " " + driver.find_element(By.TAG_NAME, "body").text).lower()
            if expected in combined or any(w in combined for w in ("success", "saved", "updated", "created")):
                return True, f"Notification verified: {toast_text.strip() or expected}"
            return _skip_or_fail(
                step,
                f"Expected a toast/notification containing '{expected}'; "
                f"found: {toast_text.strip() or '(no toast text visible)'}",
            )

        el = _find_element(step, locators)
        if el is None:
            return _skip_or_fail(step, f"'{step.object_name}' not found — continuing")

        if action in ("updaterecord", "deleterecord", "approval", "filterdata"):
            action = "performclick"

        if action in ("settext", "setpassword"):
            value = step.input_value
            if value == "********":
                value = password
            obj_lower = step.object_name.lower()
            if locators.get("role") and any(h in obj_lower for h in ("user", "name", "email", "login")):
                fill_username_and_trigger_role(driver, el, value)
            else:
                try:
                    el.clear()
                except Exception:  # noqa: BLE001
                    pass
                el.send_keys(value)
            return True, f"Entered text in '{step.object_name}'"

        if action in ("performclick", "click"):
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.2)
            try:
                el.click()
            except Exception:  # noqa: BLE001
                driver.execute_script("arguments[0].click();", el)
            time.sleep(0.8)
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:  # noqa: BLE001
                pass
            return True, f"Clicked '{step.object_name}'"

        if action == "performselect":
            select_el = el
            if step.object_name.lower() == "role" or locators.get("role"):
                select_el = wait_role_select_enabled(driver) or el
            select = Select(select_el)
            try:
                select.select_by_visible_text(step.input_value)
            except Exception:  # noqa: BLE001
                options = [o for o in select.options if (o.text or "").strip()]
                if options:
                    select.select_by_visible_text(options[0].text)
                else:
                    return _skip_or_fail(step, f"No options in '{step.object_name}' — continuing")
            time.sleep(1.0)
            return True, f"Selected '{step.input_value}' in '{step.object_name}'"

        return _skip_or_fail(step, f"Unknown action: {step.action}")

    except Exception as exc:  # noqa: BLE001
        return _skip_or_fail(step, f"{step.object_name} — {exc}")


def _is_login_scenario(scenario: ScenarioDef) -> bool:
    return scenario.id == "TC_AUTO_01"


def run_scenario(
    scenario: ScenarioDef,
    discovery: DiscoveryResult,
    password: str,
    logger: ExecutionLogger,
    fresh_login_before: bool = False,
    role_hint: str = "",
) -> TestResult:
    started = datetime.now()
    set_test_case(scenario.id, scenario.title)
    logger.info(f"Running {scenario.id}: {scenario.title}")

    if fresh_login_before:
        from uts_engine.automation.session_reset import perform_login_from_discovery

        logger.info(f"{scenario.id}: fresh login before scenario")
        perform_login_from_discovery(discovery, password, logger, role_hint=role_hint)

    locators = dict(discovery.locators)
    locators["_login_url"] = discovery.login_url
    set_dynamic_locators(locators)

    step_context: dict = {"vars": {}, "logger": logger, "terminate": False}

    steps_results = []
    total_steps = len(scenario.steps)
    for step in scenario.steps:
        try:
            from uts_engine.job_control import raise_if_stopped

            raise_if_stopped()
        except ImportError:
            pass
        except Exception as stop_exc:
            if stop_exc.__class__.__name__ == "JobStopped":
                logger.info(f"{scenario.id}: stopped by user at step {step.step_no}")
                break
            raise
        if step_context.get("terminate"):
            break
        if step.locator_by and step.locator_value:
            register_step_locator(step.object_name, step.locator_by, step.locator_value)

        def make_exec(s=step, ctx=step_context):
            def _run():
                return _execute_step(s, locators, password, ctx)

            return _run

        steps_results.append(
            run_step(
                logger,
                step.step_no,
                step.action,
                step.object_name,
                step.input_value,
                make_exec(),
                tc_id=scenario.id,
                tc_title=scenario.title,
                total_steps=total_steps,
            )
        )

    failed = [s for s in steps_results if s.status == "FAIL"]
    # Clicks that were soft-skipped must not count as a full PASS. verify/
    # notification are already critical via _is_critical_step (so a real
    # SKIP: from them means _skip_or_fail already downgraded ok=False, i.e.
    # they show up in `failed` above, not here) — listed anyway as
    # belt-and-braces for any other path that can still emit a bare SKIP
    # status for one of these two actions.
    skipped_required = [
        s
        for s in steps_results
        if s.status == "SKIP"
        and str(s.action).lower()
        in {"performclick", "click", "settext", "setpassword", "performselect", "verify", "notification"}
    ]
    status = "FAIL" if failed or skipped_required else "PASS"
    ended = datetime.now()

    return TestResult(
        tc_id=scenario.id,
        title=scenario.title,
        test_type="automation",
        status=status,
        steps=steps_results,
        started_at=started.isoformat(timespec="seconds"),
        ended_at=ended.isoformat(timespec="seconds"),
        duration_ms=round((ended - started).total_seconds() * 1000, 2),
        error=failed[0].message if failed else "",
    )


def run_all_automation(
    discovery: DiscoveryResult,
    password: str,
    logger: ExecutionLogger,
    logout_after_each: bool = True,
    continue_on_failure: bool = True,
    role_hint: str = "",
    run_modules_only: list[str] | None = None,
    run_test_cases_only: list[str] | None = None,
) -> list[TestResult]:
    from uts_engine.automation.session_reset import prepare_fresh_session, teardown_after_test

    results = []
    auto_scenarios = [s for s in discovery.scenarios if s.type in AUTOMATION_TYPES]

    if run_modules_only:
        wanted = {m.lower() for m in run_modules_only}

        def _keep(scenario: ScenarioDef) -> bool:
            mod = (scenario.module or "").strip().lower()
            if not mod or mod in ("login", "core"):
                return False
            return mod in wanted or any(w in mod for w in wanted)

        auto_scenarios = [s for s in auto_scenarios if _keep(s)]
        logger.info(f"Cycle 2: running {len(auto_scenarios)} module functional test(s) only")

    if run_test_cases_only:
        wanted_cases = {str(tc_id).strip().lower() for tc_id in run_test_cases_only}
        auto_scenarios = [
            scenario
            for scenario in auto_scenarios
            if scenario.id.lower() in wanted_cases
        ]
        logger.info(f"Selected execution: running {len(auto_scenarios)} chosen test case(s)")

    for scenario in auto_scenarios:
        try:
            from uts_engine.job_control import JobStopped, raise_if_stopped

            raise_if_stopped()
        except ImportError:
            JobStopped = None  # type: ignore
        except Exception as stop_exc:
            if stop_exc.__class__.__name__ == "JobStopped":
                logger.info("Automation stopped by user — remaining scenarios skipped")
                break
            raise

        logger.info("")
        logger.executing(f"Starting {scenario.id}: {scenario.title}")

        needs_fresh_login = scenario.id != "TC_AUTO_01" and not _is_login_scenario(scenario)
        if needs_fresh_login and logout_after_each:
            prepare_fresh_session(discovery, password, logger, role_hint=role_hint)

        try:
            result = run_scenario(
                scenario,
                discovery,
                password,
                logger,
                fresh_login_before=False,
                role_hint=role_hint,
            )

            if result.status == "FAIL" and continue_on_failure and not _is_login_scenario(scenario):
                try:
                    from uts_engine.job_control import raise_if_stopped

                    raise_if_stopped()
                except ImportError:
                    pass
                except Exception as stop_exc:
                    if stop_exc.__class__.__name__ == "JobStopped":
                        results.append(result)
                        logger.info("Automation stopped by user after failure — skipping retry")
                        break
                    raise
                # Only re-login if we can actually log back in. On a session the
                # customer supplied interactively there are no credentials, so a
                # "fresh session" here signs us out for good and every later
                # scenario runs against the login page.
                if logout_after_each:
                    logger.info(f"{scenario.id} failed — fresh login and retry explore scenario once")
                    prepare_fresh_session(discovery, password, logger, role_hint=role_hint)
                else:
                    logger.info(f"{scenario.id} failed — retrying once on the current session")
                retry = run_scenario(
                    scenario, discovery, password, logger, fresh_login_before=False, role_hint=role_hint
                )
                if retry.status == "PASS":
                    logger.info(f"{scenario.id} retry succeeded")
                    result = retry
                else:
                    logger.info(f"{scenario.id} retry also failed — moving to next scenario (no halt)")

            results.append(result)
            logger.info(f"Completed {scenario.id} => {result.status}")
            if result.status == "FAIL" and continue_on_failure:
                logger.info(f"{scenario.id} failed — continuing to next test case (no halt)")
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "JobStopped":
                logger.info(f"{scenario.id}: stopped by user")
                break
            logger.fail(f"{scenario.id} crashed: {exc}")
            ended = datetime.now()
            results.append(
                TestResult(
                    tc_id=scenario.id,
                    title=scenario.title,
                    test_type="automation",
                    status="FAIL",
                    error=str(exc),
                    ended_at=ended.isoformat(timespec="seconds"),
                )
            )
            if not continue_on_failure:
                break
        finally:
            if logout_after_each:
                logger.info(f"{scenario.id}: logout after test — preparing clean session for next scenario")
                teardown_after_test(discovery, logger)

    return results
