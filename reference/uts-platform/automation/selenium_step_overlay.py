"""Show automation steps live inside the browser window."""

from __future__ import annotations

import json
import time

from automation.selenium_session import get_driver, is_selenium_enabled, load_selenium_config

_current_tc = "AUTOMATION"
_current_title = ""
_last_highlighted = None
_extra_locators: dict[str, dict[str, str]] = {}

def set_dynamic_locators(locators: dict[str, dict[str, str]]) -> None:
    global _extra_locators
    _extra_locators = dict(locators)


def register_step_locator(object_name: str, by: str, value: str) -> str:
    key = object_name.lower().replace(" ", "_")[:40]
    _extra_locators[key] = {"by": by, "value": value}
    return key


def clear_dynamic_locators() -> None:
    global _extra_locators
    _extra_locators = {}


INJECT_SCRIPT = """
if (!document.getElementById('uts-step-overlay')) {
  var panel = document.createElement('div');
  panel.id = 'uts-step-overlay';
  panel.innerHTML = `
    <div id="uts-step-header">UTS Automation — Live Steps</div>
    <div id="uts-step-tc"></div>
    <div id="uts-step-num"></div>
    <div id="uts-step-action"></div>
    <div id="uts-step-detail"></div>
    <div id="uts-step-status"></div>
  `;
  document.body.appendChild(panel);
  var style = document.createElement('style');
  style.textContent = `
    #uts-step-overlay {
      position: fixed; bottom: 0; left: 0; right: 0; z-index: 99999;
      background: linear-gradient(135deg, #1a2b4a 0%, #2d4a7a 100%);
      color: #fff; padding: 14px 24px; font-family: Segoe UI, Arial, sans-serif;
      box-shadow: 0 -4px 20px rgba(0,0,0,.3); border-top: 3px solid #f59e0b;
      pointer-events: none;
    }
    #uts-step-header { font-size: 11px; text-transform: uppercase; opacity: .8; margin-bottom: 4px; }
    #uts-step-tc { font-size: 13px; font-weight: 600; color: #93c5fd; }
    #uts-step-num { font-size: 22px; font-weight: bold; margin: 4px 0; }
    #uts-step-action { font-size: 16px; font-weight: 600; }
    #uts-step-detail { font-size: 13px; opacity: .9; margin-top: 4px; }
    #uts-step-status {
      display: inline-block; margin-top: 8px; padding: 4px 12px; border-radius: 4px;
      font-size: 12px; font-weight: bold; text-transform: uppercase;
    }
    #uts-step-status.running { background: #f59e0b; color: #1a2b4a; }
    #uts-step-status.pass { background: #10b981; color: #fff; }
    #uts-step-status.fail { background: #ef4444; color: #fff; }
    .uts-highlight { outline: 3px solid #f59e0b !important; outline-offset: 2px !important;
                    box-shadow: 0 0 12px rgba(245,158,11,.6) !important; }
  `;
  document.head.appendChild(style);
}
"""

UPDATE_SCRIPT = """
var tc = arguments[0], title = arguments[1], step = arguments[2],
    action = arguments[3], detail = arguments[4], status = arguments[5];
document.getElementById('uts-step-tc').textContent = tc + (title ? ' — ' + title : '');
document.getElementById('uts-step-num').textContent = 'Step ' + step;
document.getElementById('uts-step-action').textContent = action;
document.getElementById('uts-step-detail').textContent = detail;
var st = document.getElementById('uts-step-status');
st.textContent = status;
st.className = status.toLowerCase();
"""


def set_test_case(tc_id: str, title: str = "") -> None:
    global _current_tc, _current_title
    _current_tc = tc_id
    _current_title = title
    if is_selenium_enabled():
        _ensure_overlay()


def _ensure_overlay() -> None:
    try:
        get_driver().execute_script(INJECT_SCRIPT)
    except Exception:  # noqa: BLE001
        pass


def _step_delay() -> None:
    cfg = load_selenium_config()
    ms = int(cfg.get("step_display_delay_ms", 900))
    if ms > 0:
        time.sleep(ms / 1000)


def show_step(
    step_no: int,
    action: str,
    object_name: str,
    input_value: str = "",
    status: str = "RUNNING",
    highlight_locator_key: str | None = None,
    detail_override: str | None = None,
) -> None:
    if not is_selenium_enabled():
        return

    detail = detail_override or f"Object: {object_name}"
    if not detail_override and input_value:
        detail += f"  |  Input: {input_value}"

    try:
        driver = get_driver()
        _ensure_overlay()
        driver.execute_script(
            UPDATE_SCRIPT,
            _current_tc,
            _current_title,
            step_no,
            action,
            detail,
            status,
        )

        if highlight_locator_key and status == "RUNNING":
            _highlight_element(highlight_locator_key)

        if status == "RUNNING":
            _step_delay()
    except Exception:  # noqa: BLE001
        pass


def show_result(step_no: int, action: str, object_name: str, passed: bool, message: str) -> None:
    status = "PASS" if passed else "FAIL"
    show_step(step_no, action, object_name, status=status, detail_override=message)
    if status == "PASS":
        _step_delay()


def _highlight_element(locator_key: str) -> None:
    global _last_highlighted
    try:
        from selenium.webdriver.common.by import By
        from automation.selenium_actions import wait_visible

        driver = get_driver()
        if locator_key in _extra_locators:
            loc = _extra_locators[locator_key]
            by_map = {"id": By.ID, "name": By.NAME, "css": By.CSS_SELECTOR, "xpath": By.XPATH}
            by = by_map.get(loc["by"], By.ID)
            el = driver.find_element(by, loc["value"])
        else:
            el = wait_visible(locator_key)

        if _last_highlighted:
            try:
                driver.execute_script(
                    "arguments[0].classList.remove('uts-highlight')", _last_highlighted
                )
            except Exception:  # noqa: BLE001
                pass

        driver.execute_script("arguments[0].classList.add('uts-highlight')", el)
        driver.execute_script(
            "arguments[0].scrollIntoView({behavior:'smooth', block:'center'})", el
        )
        _last_highlighted = el
    except Exception:  # noqa: BLE001
        pass


def locator_key_for_object(object_name: str) -> str | None:
    """Map test object name to selenium locator key."""
    key = object_name.lower().strip()
    normalized = key.replace(" ", "_")[:40]
    if normalized in _extra_locators:
        return normalized
    if key.replace(" ", "_")[:40] in _extra_locators:
        return key.replace(" ", "_")[:40]
    norm = key.replace(" ", "").replace("_", "")
    mapping = {
        "loginpage": "username",
        "username": "username",
        "password": "password",
        "login": "login_button",
        "dashboard": "dashboard",
        "transfersmenu": "transfers_menu",
        "transferbetweenmyaccounts": "transfer_self_link",
        "transferscreen": "transfer_screen",
        "pagetitle": "page_title",
        "sendfrom": "send_from",
        "sendto": "send_to",
        "amount": "amount",
        "transferdate": "transfer_date",
        "frequency": "frequency",
        "message": "message",
        "continue": "continue_button",
        "continuebutton": "continue_button",
        "reviewscreen": "review_screen",
        "confirm": "confirm_button",
        "confirmbutton": "confirm_button",
        "successmessage": "success_message",
    }
    return mapping.get(key) or mapping.get(normalized)
