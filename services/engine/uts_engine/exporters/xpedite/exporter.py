"""Convert UTS discovery scenarios to Converter Dynamic / Xpedite format."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from uts_engine.discovery.discovery import DiscoveryResult, ScenarioDef, StepDef
from uts_engine.workdir import data_root

# services/engine/, three levels above this file (uts_engine/exporters/xpedite/).
ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_FILE = ROOT / "config" / "xpedite.json"


def _sanitize(name: str) -> str:
    clean = str(name).replace("-", "_")
    clean = re.sub(r"[^a-zA-Z0-9_ ]", "", clean)
    return clean.strip().replace(" ", "_")


def _map_action(step: StepDef, password: str) -> tuple[str, str, str]:
    """Return (action, input_value, object_name) for Xpedite step."""
    action = step.action
    obj = step.object_name
    val = step.input_value

    if action == "Navigate":
        return "InvokeURL", f"<ApplicationURL>:{val}", "ApplicationURL"

    if action == "SetText":
        if "password" in obj.lower():
            return "SetPassword", f"<Password>:{password}", "Password"
        if "user" in obj.lower():
            return "SetText", f"<Username>:{val}", "Username"
        var = _sanitize(obj)
        return "SetText", f"<{var}>:{val}", obj

    if action == "PerformSelect":
        var = _sanitize(obj)
        return "PerformSelect", f"<{var}>:{val}", obj

    if action == "PerformClick":
        return "PerformClick", "", obj.replace(" Button", "").replace(" button", "")

    if action == "Verify":
        expected = step.expected or val or obj
        return "VerifyNonEditableText", f"<ExpectedResult>:{expected}", "NonEditableText"

    if action in ("UpdateRecord", "DeleteRecord", "Approval", "FilterData"):
        return "PerformClick", "", obj.replace(" Button", "").replace(" button", "")

    if action == "Delay":
        return "Wait", val or "1", "Delay"

    if action == "LogMessage":
        return "Log", val or obj, "LogMessage"

    if action == "Notification":
        expected = step.expected or val or obj
        return "VerifyNonEditableText", f"<ExpectedResult>:{expected}", "NonEditableText"

    return "PerformClick", val, obj


def _make_step(object_name: str, action: str, input_value: str = "", description: str = "") -> dict:
    return {
        "object_name": object_name,
        "action": action,
        "input_value": input_value,
        "expected_value": "True" if action == "VerifyNonEditableText" else "",
        "description": description or object_name,
    }


def _is_login_step(step: StepDef) -> bool:
    obj = (step.object_name or "").lower()
    if any(token in obj for token in ("search", "filter", "find")):
        return False
    if step.action == "SetText" and any(
        h in obj for h in ("username", "user name", "email", "login", "uid", "account", "phone", "mobile")
    ):
        return True
    if step.action in ("SetText", "SetPassword") and "pass" in obj:
        return True
    if "password" in obj:
        return True
    if step.action == "PerformClick" and any(
        h in obj for h in ("login", "sign in", "signin", "submit", "log in", "sign-in")
    ):
        return True
    if step.action == "PerformSelect" and "role" in obj:
        return True
    # Explicit names we emit ourselves
    if obj in ("username", "password", "login", "sign in"):
        return True
    return False


def _is_protected_bc(name: str) -> bool:
    n = (name or "").lower().replace(" ", "_")
    return n in ("launch_application", "invokeurl", "invoke_url", "login") or "launch" in n


def _dynamic_bc_name(step: StepDef) -> str:
    """Name business BC from the live step/object — fully dynamic."""
    return _sanitize(step.object_name) or _sanitize(step.action) or "Business_Flow"



def _scenario_business_bc_name(scenario: ScenarioDef) -> str:
    """One BC name for the scenario business flow (not per click)."""
    title = scenario.title or scenario.id or "Business_Flow"
    # Strip app suffix " — AppName"
    title = title.split(" — ")[0].split(" - ")[0].strip()
    # "Create Lead: Transfers" -> use module part (Create Lead) for BC name
    if ":" in title:
        module_part = title.split(":", 1)[0].strip()
        if module_part:
            name = _sanitize(module_part)
            if name:
                return name[:60]
    title = re.sub(r"^(Explore|Form input)\s+", "", title, flags=re.IGNORECASE)
    name = _sanitize(title) or "Business_Flow"
    return name[:60]


def _verify_group_bc_name(verify_steps: list[dict]) -> str:
    """Name verify BC from expected text (e.g. Dashboard) — dynamic like screenshot."""
    blob = " ".join(
        f"{s.get('description', '')} {s.get('input_value', '')}" for s in verify_steps
    ).lower()
    if "dashboard" in blob:
        return "Dashboard"
    if "home" in blob or "post-login" in blob or "logged-in" in blob:
        return "Dashboard"
    # First meaningful word from description
    for s in verify_steps:
        desc = (s.get("description") or "").strip()
        if desc and desc.lower() not in ("noneditabletext", "verify"):
            return _sanitize(desc)[:40] or "Verify_Result"
    return "Verify_Result"


def _screen_block_name_from_step(step: StepDef) -> str | None:
    """Infer a BC name when a step clearly moves the flow to a new screen/page."""
    expected = (step.expected or "").strip()
    object_name = (step.object_name or "").strip()

    for pattern in (
        r"Opened '([^']+)' module",
        r'Opened "([^"]+)" module',
        r"Opened '([^']+)' sub-page",
        r'Opened "([^"]+)" sub-page',
        r"Opened '([^']+)' screen",
        r'Opened "([^"]+)" screen',
        r"Opened '([^']+)' page",
        r'Opened "([^"]+)" page',
    ):
        match = re.search(pattern, expected, flags=re.IGNORECASE)
        if match:
            return _sanitize(match.group(1)) or None

    if step.action == "PerformClick" and object_name:
        lower_expected = expected.lower()
        if any(token in lower_expected for token in ("opened", "screen", "page", "module", "tab", "sub-page")):
            return _sanitize(object_name) or None
    return None


def _collapse_one_line_bcs(blocks: list[dict]) -> list[dict]:
    """
    Screenshot form:
    BC_Launch_Application → BC_Login → BC_<BusinessFlow> → …

    Related non-protected business steps are folded into one BC
    (complete business process), not one BC per click/step.
    """
    if not blocks:
        return blocks

    result: list[dict] = []
    for block in blocks:
        steps = [s for s in (block.get("steps") or []) if s]
        if not steps:
            continue
        name = str(block.get("bc_name") or "Business_Flow")
        if "launch" in name.lower() or name.lower() in ("invokeurl", "invoke_url"):
            name = "Launch_Application"
        if name.lower() in ("username", "password"):
            if result and str(result[-1].get("bc_name") or "").lower() == "login":
                result[-1]["steps"].extend(steps)
            else:
                result.append({"bc_name": "Login", "steps": steps})
            continue
        # Same-name merge
        if (
            result
            and str(result[-1].get("bc_name") or "").lower() == name.lower()
            and not _is_protected_bc(name)
        ):
            result[-1]["steps"].extend(steps)
            continue
        result.append({"bc_name": name, "steps": steps})

    return result


def scenario_to_functional_blocks(scenario: ScenarioDef, password: str) -> list[dict]:
    """
    Match Xpedite BC form from screenshot:
    1. BC_Launch_Application — Action=InvokeURL, Object=ApplicationURL
    2. BC_Login — SetText Username, SetPassword Password, PerformClick Sign in/Login
    3. Then split business BCs screen-wise instead of flattening the full flow
    """
    blocks: list[dict] = []
    login_steps: list[dict] = []
    business_steps: list[dict] = []
    flow_bc_name = _scenario_business_bc_name(scenario)
    business_name: str | None = None
    pending_verify: list[dict] = []

    def flush_login():
        nonlocal login_steps
        if login_steps:
            blocks.append({"bc_name": "Login", "steps": login_steps})
            login_steps = []

    def flush_business():
        nonlocal business_steps, business_name
        if business_steps:
            blocks.append({
                "bc_name": business_name or "Business_Flow",
                "steps": business_steps,
            })
            business_steps = []
            business_name = None

    def flush_pending_verify():
        nonlocal pending_verify
        if pending_verify:
            blocks.append({
                "bc_name": _verify_group_bc_name(pending_verify),
                "steps": pending_verify,
            })
            pending_verify = []

    for step in scenario.steps:
        if step.action == "Navigate":
            flush_business()
            flush_login()
            flush_pending_verify()
            action, input_val, obj = _map_action(step, password)
            # Form 1: BC_Launch_Application / InvokeURL
            blocks.append({
                "bc_name": "Launch_Application",
                "steps": [_make_step(
                    "ApplicationURL",
                    "InvokeURL",
                    input_val,
                    "Launch application URL",
                )],
            })
            continue

        if _is_login_step(step):
            flush_business()
            flush_pending_verify()
            action, input_val, obj = _map_action(step, password)
            # Form 2: normalize login objects like screenshot
            if action == "SetPassword":
                login_steps.append(_make_step("Password", "SetPassword", input_val, "Password"))
            elif action == "SetText":
                login_steps.append(_make_step("Username", "SetText", input_val, "Username"))
            elif action == "PerformClick":
                btn = (step.object_name or "Login").strip() or "Login"
                # Prefer visible label (Sign in / Login)
                login_steps.append(_make_step(btn, "PerformClick", "", btn))
            elif action == "PerformSelect":
                login_steps.append(_make_step("Role", "PerformSelect", input_val, step.object_name or "Role"))
            else:
                login_steps.append(_make_step(obj, action, input_val, step.object_name))
            continue

        if step.action == "Verify":
            flush_login()
            action, input_val, obj = _map_action(step, password)
            # Form 3 style: NonEditableText + VerifyNonEditableText + Expected True
            pending_verify.append(_make_step(
                "NonEditableText",
                "VerifyNonEditableText",
                input_val,
                step.expected or step.object_name or "Verify",
            ))
            continue

        # Dynamic business BCs after Launch + Login
        flush_login()
        action, input_val, obj = _map_action(step, password)
        mapped = _make_step(obj, action, input_val, step.object_name)
        dyn_name = _dynamic_bc_name(step)
        screen_name = _screen_block_name_from_step(step)

        if screen_name and business_steps:
            flush_business()

        if step.action == "PerformClick":
            if pending_verify:
                if business_name is None:
                    business_name = screen_name or flow_bc_name
                business_steps.extend(pending_verify)
                pending_verify = []
            if business_name is None:
                business_name = screen_name or flow_bc_name or dyn_name
            elif screen_name and business_name != screen_name:
                flush_business()
                business_name = screen_name
            business_steps.append(mapped)
            continue

        if pending_verify:
            if business_name is None:
                business_name = flow_bc_name
            business_steps.extend(pending_verify)
            pending_verify = []
        if business_name is None:
            business_name = screen_name or flow_bc_name or dyn_name
        business_steps.append(mapped)

    flush_login()
    flush_business()
    flush_pending_verify()
    return _collapse_one_line_bcs(blocks)


def _scenario_has_login(scenario: ScenarioDef) -> bool:
    return any(_is_login_step(s) or s.action == "Navigate" for s in scenario.steps)


def _build_login_prefix_steps(discovery: DiscoveryResult) -> list[StepDef]:
    """Launch + login steps injected into every test case."""
    locators = discovery.locators or {}
    user = locators.get("username", {})
    pwd = locators.get("password", {})
    submit_key = next(
        (k for k in locators if "login" in k.lower() or k == "login_button"),
        None,
    )
    submit = locators.get(submit_key or "", {})

    steps = [
        StepDef(1, "Navigate", "Application URL", discovery.url, expected="Login page loads"),
        StepDef(
            2,
            "SetText",
            "Username",
            discovery.username,
            user.get("by", ""),
            user.get("value", ""),
            "Username entered",
        ),
        StepDef(
            3,
            "SetText",
            "Password",
            "********",
            pwd.get("by", ""),
            pwd.get("value", ""),
            "Password entered",
        ),
    ]
    if submit:
        steps.append(
            StepDef(
                4,
                "PerformClick",
                "Login",
                "",
                submit.get("by", ""),
                submit.get("value", ""),
                "User lands on home/dashboard",
            )
        )
    else:
        steps.append(StepDef(4, "PerformClick", "Login", "", expected="User lands on home/dashboard"))
    return steps


def ensure_scenario_has_login(scenario: ScenarioDef, discovery: DiscoveryResult) -> ScenarioDef:
    """Every test case must include login steps."""
    if _scenario_has_login(scenario):
        return scenario
    prefix = _build_login_prefix_steps(discovery)
    offset = len(prefix)
    rest = [
        StepDef(
            step_no=offset + i,
            action=s.action,
            object_name=s.object_name,
            input_value=s.input_value,
            locator_by=s.locator_by,
            locator_value=s.locator_value,
            expected=s.expected,
        )
        for i, s in enumerate(scenario.steps, start=1)
    ]
    return ScenarioDef(
        id=scenario.id,
        type=scenario.type,
        title=scenario.title,
        steps=prefix + rest,
    )


def _xpedite_tc_base_name(title: str, scenario_id: str) -> str:
    """Title part before em-dash, sanitized — keeps hyphens inside names like Post-login."""
    base = re.split(r"[\u2014—]", title, maxsplit=1)[0].strip()
    return _sanitize(base) or scenario_id


def _xpedite_tc_output_name(title: str, scenario_id: str) -> str:
    base = _xpedite_tc_base_name(title, scenario_id)
    if base.upper().startswith("TC_"):
        return base
    return f"TC_{base}"


def discovery_scenario_to_generator(
    scenario: ScenarioDef,
    discovery: DiscoveryResult,
    password: str,
) -> dict:
    # Rule: every test case must include login
    scenario = ensure_scenario_has_login(scenario, discovery)

    tc_base = _xpedite_tc_base_name(scenario.title, scenario.id)
    tc_output_name = _xpedite_tc_output_name(scenario.title, scenario.id)

    test_data = (
        f"<ApplicationURL>:{discovery.url} "
        f"<Username>:{discovery.username} "
        f"<Password>:{password}"
    )

    return {
        "tc_id": scenario.id,
        "tc_id_name": tc_output_name,
        "name": tc_output_name,
        "display_name": scenario.title,
        "test_data": test_data,
        "description": scenario.title,
        "functional_blocks": scenario_to_functional_blocks(scenario, password),
    }


def load_xpedite_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {
        "converter_dynamic_path": "",
        "template_path": "templates/xpedite",
        "output_path": "xpedite-output",
        "export_manual_scenarios": False,
        "export_automation_scenarios": True,
    }


def _load_xpedite_generator(converter_path: Path):
    """Load Xpedite XML generator — bundled copy first, optional external path second."""
    import importlib.util

    bundled = ROOT / "uts_engine" / "exporters" / "xpedite" / "generator_engine.py"
    candidates: list[Path] = [bundled]
    if converter_path.is_dir():
        candidates.append(converter_path / "generator.py")

    gen_path = next((p for p in candidates if p.is_file()), None)
    if gen_path is None:
        raise FileNotFoundError(
            "Xpedite generator not found. Expected bundled file at "
            f"{bundled}. "
            "Optional: set converter_dynamic_path in config/xpedite.json "
            "to a folder containing generator.py."
        )

    # generator_engine imports excel_writer from project root
    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    spec = importlib.util.spec_from_file_location("xpedite_generator_engine", gen_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Xpedite generator from {gen_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def _clean_xpedite_output(output_path: Path) -> None:
    """Remove stale TC/BPW/BC/XML folders so output matches current export only."""
    if not output_path.exists():
        return
    for item in list(output_path.iterdir()):
        name = item.name
        try:
            if item.is_file() and name.startswith("TC_") and name.endswith(".xml"):
                item.unlink()
            elif item.is_dir() and name.startswith("TC_"):
                shutil.rmtree(item, ignore_errors=True)
        except OSError:
            pass


def export_discovery_to_xpedite(
    discovery: DiscoveryResult,
    password: str,
) -> Path:
    """Generate TC/BPW/BC XML + TestData.xlsx in Converter Dynamic format."""
    cfg = load_xpedite_config()
    output_path = data_root() / cfg.get("output_path", "xpedite-output")
    template_path = ROOT / cfg.get("template_path", "templates/xpedite")
    converter_path = Path(cfg.get("converter_dynamic_path", ""))

    output_path.mkdir(parents=True, exist_ok=True)
    _clean_xpedite_output(output_path)

    xpedite_gen = _load_xpedite_generator(converter_path)

    xpedite_gen.OUTPUT_PATH = str(output_path)
    xpedite_gen.TEMPLATE_PATH = str(template_path)
    xpedite_gen.TEMPLATE_SEARCH_PATHS = [str(template_path)]
    xpedite_gen.SHARED_TESTDATA_FILE = "TestData.xlsx"

    scenarios = []
    for scenario in discovery.scenarios:
        if scenario.type != "automation":
            continue
        if scenario.type == "manual" and not cfg.get("export_manual_scenarios", False):
            continue
        if scenario.type == "automation" and not cfg.get("export_automation_scenarios", True):
            continue
        if not scenario.steps:
            continue
        gen_scenario = discovery_scenario_to_generator(scenario, discovery, password)
        if gen_scenario.get("functional_blocks"):
            scenarios.append(gen_scenario)

    if not scenarios:
        raise ValueError("No scenarios to export to Xpedite format.")

    # Use UTS ExcelWriter (RowNum starts at 2) — not Converter Dynamic copy on sys.path
    import importlib.util

    uts_excel_path = ROOT / "excel_writer.py"
    spec = importlib.util.spec_from_file_location("uts_excel_writer", uts_excel_path)
    uts_excel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(uts_excel)
    ExcelWriter = uts_excel.ExcelWriter

    def generate_shared_testdata_workbook(scenarios_list):
        template = template_path / "TestData.xlsx"
        output_file = output_path / "TestData.xlsx"
        try:
            ExcelWriter(str(template)).write(scenarios_list, str(output_file))
        except PermissionError:
            fallback = output_path / "TestData_new.xlsx"
            ExcelWriter(str(template)).write(scenarios_list, str(fallback))
            print(
                f"WARNING: Close TestData.xlsx in Excel and re-run. "
                f"Wrote {fallback.name} instead."
            )
            return str(fallback)
        return str(output_file)

    xpedite_gen.generate_shared_testdata_workbook = generate_shared_testdata_workbook
    xpedite_gen.generate_shared_testdata_workbook(scenarios)
    for scenario in scenarios:
        xpedite_gen.normalize_scenario_steps(scenario)
        xpedite_gen.generate_suite(scenario)

    return output_path
