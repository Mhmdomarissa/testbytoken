"""Generate standalone Python Selenium scripts from UTS discovery results."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uts_engine.discovery.discovery import DiscoveryResult, ScenarioDef

BY_MAP = {
    "id": "By.ID",
    "name": "By.NAME",
    "css": "By.CSS_SELECTOR",
    "css selector": "By.CSS_SELECTOR",
    "xpath": "By.XPATH",
    "link text": "By.LINK_TEXT",
    "partial link text": "By.PARTIAL_LINK_TEXT",
}


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value or "step").strip("_") or "step"


def _locator_expr(by: str, value: str) -> str:
    by_key = (by or "xpath").lower()
    by_const = BY_MAP.get(by_key, "By.XPATH")
    escaped = (value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f"({by_const}, \"{escaped}\")"


def _step_code(step: dict, indent: str = "        ") -> str:
    action = (step.get("action") or "").lower()
    obj = step.get("object_name") or "element"
    by = step.get("locator_by") or ""
    val = step.get("locator_value") or ""
    inp = step.get("input_value") or ""
    loc = _locator_expr(by, val) if val else None

    if action in ("settext", "setpassword"):
        return f'{indent}driver.find_element(*{loc}).clear()\n{indent}driver.find_element(*{loc}).send_keys("{inp}")\n'
    if action in ("performclick", "click", "save"):
        return f"{indent}WebDriverWait(driver, 20).until(EC.element_to_be_clickable({loc})).click()\n"
    if action == "performselect":
        return (
            f"{indent}Select(driver.find_element(*{loc})).select_by_visible_text(\"{inp}\")\n"
            if inp
            else f"{indent}Select(driver.find_element(*{loc})).select_by_index(1)\n"
        )
    if action == "verify":
        return (
            f'{indent}assert "{inp}" in driver.page_source, '
            f'"Expected text not found: {obj}"\n'
        )
    if action == "delay":
        seconds = inp or "1"
        return f"{indent}time.sleep(float({seconds}))\n"
    if action == "logmessage":
        return f'{indent}print("[LOG]", "{obj}", "{inp}")\n'
    if action == "navigate":
        return f'{indent}driver.get("{inp}")\n' if inp else ""
    return f'{indent}# {action}: {obj}\n'


def generate_test_script(
    scenario: ScenarioDef,
    app_url: str,
    username: str,
    password: str,
) -> str:
    from dataclasses import asdict

    steps_code = "".join(_step_code(asdict(st)) for st in (scenario.steps or []))
    tc_id = _safe_name(scenario.id)
    return f'''"""Auto-generated Selenium test: {scenario.title}"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

APP_URL = "{app_url}"
USERNAME = "{username}"
PASSWORD = "{password}"


def run_test():
    driver = webdriver.Chrome()
    driver.maximize_window()
    try:
        driver.get(APP_URL)
        time.sleep(1)
{steps_code}
        print("PASS: {scenario.id}")
    except Exception as exc:
        print(f"FAIL: {scenario.id} — {{exc}}")
        driver.save_screenshot("{tc_id}_failure.png")
        raise
    finally:
        driver.quit()


if __name__ == "__main__":
    run_test()
'''


def generate_selenium_from_discovery(
    discovery: DiscoveryResult,
    output_dir: str | Path,
) -> dict[str, str]:
    """Write one .py file per automation scenario. Returns {{tc_id: path}}."""
    out = Path(output_dir)
    tests_dir = out / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    conftest = tests_dir / "conftest.py"
    if not conftest.exists():
        conftest.write_text(
            '"""Shared fixtures for generated Selenium tests."""\n',
            encoding="utf-8",
        )

    readme = out / "README.txt"
    readme.write_text(
        "Generated Selenium scripts — run any test with: python tests/TC_POS_01.py\n",
        encoding="utf-8",
    )

    paths: dict[str, str] = {}
    from uts_engine.discovery.discovery import AUTOMATION_TYPES

    for scenario in discovery.scenarios:
        if scenario.type not in AUTOMATION_TYPES:
            continue
        filename = f"{_safe_name(scenario.id)}.py"
        script_path = tests_dir / filename
        script_path.write_text(
            generate_test_script(
                scenario,
                discovery.url,
                discovery.username,
                "YOUR_PASSWORD_HERE",
            ),
            encoding="utf-8",
        )
        paths[scenario.id] = str(script_path)
    return paths
