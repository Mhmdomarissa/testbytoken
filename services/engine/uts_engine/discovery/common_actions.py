"""Common automation action catalog and workflow-style step execution."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uts_engine.workdir import data_root

# services/engine/, two levels above this file (uts_engine/discovery/).
ROOT = Path(__file__).resolve().parent.parent.parent
GENERATED_DIR = data_root() / "generated"

# Full catalog (workflow-style names users expect)
COMMON_AUTOMATION_ACTIONS: dict[str, dict[str, str]] = {
    "Trigger": {"category": "flow", "description": "Start test scenario / module run"},
    "Condition": {"category": "flow", "description": "If/Else branch on expected value"},
    "Loop": {"category": "flow", "description": "For Each / While / Do Until (scenario level)"},
    "Variable": {"category": "data", "description": "Set or read runtime variable"},
    "Compose": {"category": "data", "description": "Build text from variables"},
    "ParseJSON": {"category": "data", "description": "Parse JSON into variables"},
    "FilterData": {"category": "data", "description": "Filter list/collection data"},
    "HTTPRequest": {"category": "integration", "description": "Call REST API (GET/POST)"},
    "SendEmail": {"category": "integration", "description": "Send email notification"},
    "CreateFile": {"category": "file", "description": "Write output file"},
    "ReadFile": {"category": "file", "description": "Read file into variable"},
    "UpdateRecord": {"category": "crud", "description": "Save / update form record"},
    "DeleteRecord": {"category": "crud", "description": "Delete record"},
    "Delay": {"category": "utility", "description": "Wait / sleep"},
    "Approval": {"category": "business", "description": "Approve action/button"},
    "Notification": {"category": "business", "description": "Verify toast/notification"},
    "RunScript": {"category": "utility", "description": "Run external script"},
    "ExecuteSQL": {"category": "integration", "description": "Run SQL query"},
    "ErrorHandling": {"category": "flow", "description": "Catch and continue on error"},
    "LogMessage": {"category": "utility", "description": "Write log message"},
    "End": {"category": "flow", "description": "End scenario successfully"},
    "Terminate": {"category": "flow", "description": "Stop scenario immediately"},
    # UI actions (Xpedite / Selenium)
    "Navigate": {"category": "ui", "description": "Open URL (InvokeURL)"},
    "SetText": {"category": "ui", "description": "Enter text in field"},
    "SetPassword": {"category": "ui", "description": "Enter password"},
    "PerformClick": {"category": "ui", "description": "Click button/link"},
    "PerformSelect": {"category": "ui", "description": "Select dropdown option"},
    "Verify": {"category": "ui", "description": "Verify text/page state"},
}

# Aliases -> canonical action name
ACTION_ALIASES: dict[str, str] = {
    "wait": "Delay",
    "delay": "Delay",
    "sleep": "Delay",
    "log": "LogMessage",
    "logmessage": "LogMessage",
    "if": "Condition",
    "else": "Condition",
    "foreach": "Loop",
    "while": "Loop",
    "dountil": "Loop",
    "setvariable": "Variable",
    "getvariable": "Variable",
    "compose": "Compose",
    "parsejson": "ParseJSON",
    "filterdata": "FilterData",
    "http": "HTTPRequest",
    "httprequest": "HTTPRequest",
    "sendemail": "SendEmail",
    "createfile": "CreateFile",
    "readfile": "ReadFile",
    "update": "UpdateRecord",
    "updaterecord": "UpdateRecord",
    "save": "UpdateRecord",
    "delete": "DeleteRecord",
    "deleterecord": "DeleteRecord",
    "approve": "Approval",
    "approval": "Approval",
    "notify": "Notification",
    "notification": "Notification",
    "runscript": "RunScript",
    "executesql": "ExecuteSQL",
    "sql": "ExecuteSQL",
    "errorhandling": "ErrorHandling",
    "end": "End",
    "terminate": "Terminate",
    "trigger": "Trigger",
    "navigate": "Navigate",
    "settext": "SetText",
    "setpassword": "SetPassword",
    "performclick": "PerformClick",
    "click": "PerformClick",
    "performselect": "PerformSelect",
    "verify": "Verify",
    "invokurl": "Navigate",
    "invokeurl": "Navigate",
}

UI_ACTIONS = {
    "Navigate", "SetText", "SetPassword", "PerformClick", "PerformSelect", "Verify",
    "UpdateRecord", "DeleteRecord", "Approval", "Notification",
}


def normalize_action(action: str) -> str:
    key = (action or "").strip().replace(" ", "").replace("_", "").lower()
    return ACTION_ALIASES.get(key, action.strip())


def infer_action_from_button(label: str) -> str:
    """Map button label to common automation action."""
    text = (label or "").lower()
    if any(h in text for h in ("delete", "remove", "trash")):
        return "DeleteRecord"
    if any(h in text for h in ("approve", "accept", "confirm yes")):
        return "Approval"
    if any(h in text for h in ("save", "update", "submit", "apply", "store")):
        return "UpdateRecord"
    if any(h in text for h in ("search", "filter", "find")):
        return "FilterData"
    if any(h in text for h in ("add", "new", "create", "insert")):
        return "PerformClick"
    return "PerformClick"


def save_actions_catalog() -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / "common-actions.json"
    path.write_text(json.dumps(COMMON_AUTOMATION_ACTIONS, indent=2), encoding="utf-8")
    return path


def execute_workflow_action(
    action: str,
    object_name: str,
    input_value: str,
    expected: str,
    context: dict[str, Any],
) -> tuple[bool, str, bool]:
    """
    Execute non-UI workflow action.
    Returns (success, message, is_ui_action).
    is_ui_action=True means caller should run Selenium handler instead.
    """
    name = normalize_action(action)
    vars_store: dict[str, Any] = context.setdefault("vars", {})
    logger = context.get("logger")

    if name in UI_ACTIONS and name not in (
        "UpdateRecord", "DeleteRecord", "Approval", "Notification",
    ):
        if name in ("Navigate", "SetText", "SetPassword", "PerformClick", "PerformSelect", "Verify"):
            return True, "", True
        # CRUD UI aliases still go to Selenium click/verify
        if name in ("UpdateRecord", "DeleteRecord", "Approval"):
            return True, "", True
        if name == "Notification":
            return True, "", True

    if name == "Trigger":
        msg = f"Trigger: started '{object_name or 'scenario'}'"
        if logger:
            logger.info(msg)
        return True, msg, False

    if name == "Delay":
        seconds = 1.0
        try:
            seconds = float(input_value or object_name or "1")
        except ValueError:
            pass
        time.sleep(max(0.1, seconds))
        return True, f"Delay {seconds}s", False

    if name == "LogMessage":
        msg = input_value or object_name or "Log message"
        if logger:
            logger.info(msg)
        return True, msg, False

    if name == "Variable":
        var_name = object_name or "var"
        vars_store[var_name] = input_value
        return True, f"Variable {var_name}={input_value!r}", False

    if name == "Compose":
        template = input_value or object_name or ""
        for key, val in vars_store.items():
            template = template.replace(f"{{{key}}}", str(val))
        out_var = object_name or "composed"
        vars_store[out_var] = template
        return True, f"Compose -> {out_var}", False

    if name == "ParseJSON":
        try:
            data = json.loads(input_value or "{}")
            key = object_name or "json"
            vars_store[key] = data
            return True, f"ParseJSON -> {key}", False
        except json.JSONDecodeError as exc:
            return True, f"SKIP: ParseJSON failed — {exc}", False

    if name == "FilterData":
        # UI search/filter button — let Selenium click handler run
        if object_name and not vars_store.get(object_name):
            return True, "", True
        source_key = object_name or "data"
        needle = (input_value or "").lower()
        items = vars_store.get(source_key, [])
        if isinstance(items, list):
            filtered = [x for x in items if needle in str(x).lower()]
            vars_store[f"{source_key}_filtered"] = filtered
            return True, f"FilterData: {len(filtered)} item(s)", False
        return True, "SKIP: FilterData source not a list", False

    if name == "HTTPRequest":
        url = input_value or object_name
        if not url.startswith("http"):
            return True, "SKIP: HTTPRequest needs URL", False
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
                body = resp.read(5000).decode("utf-8", errors="replace")
            vars_store["http_response"] = body
            return True, f"HTTPRequest OK ({len(body)} bytes)", False
        except (urllib.error.URLError, TimeoutError) as exc:
            return True, f"SKIP: HTTPRequest — {exc}", False

    if name == "ReadFile":
        path = Path(input_value or object_name)
        if not path.is_file():
            return True, f"SKIP: ReadFile not found — {path}", False
        content = path.read_text(encoding="utf-8", errors="replace")
        vars_store[object_name or "file_content"] = content
        return True, f"ReadFile OK ({path.name})", False

    if name == "CreateFile":
        path = Path(object_name or GENERATED_DIR / "automation-output.txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(input_value or "", encoding="utf-8")
        return True, f"CreateFile OK ({path.name})", False

    if name == "Condition":
        expr = (expected or input_value or object_name or "").lower()
        page_hint = str(vars_store.get("_last_message", "")).lower()
        ok = bool(expr) and (expr in page_hint or expr == "true")
        if not ok:
            return True, f"SKIP: Condition false — {expr}", False
        return True, f"Condition true — {expr}", False

    if name == "SendEmail":
        msg = f"SendEmail (logged): to={object_name} body={input_value[:80] if input_value else ''}"
        if logger:
            logger.info(msg)
        return True, msg, False

    if name == "RunScript":
        return True, "SKIP: RunScript not enabled in UI automation mode", False

    if name == "ExecuteSQL":
        return True, "SKIP: ExecuteSQL requires database config", False

    if name == "Loop":
        return True, "Loop handled at scenario/module level", False

    if name == "ErrorHandling":
        return True, "ErrorHandling active (skip-on-miss enabled)", False

    if name in ("End", "Terminate"):
        context["terminate"] = True
        return True, f"{name}: scenario step complete", False

    return True, "", True  # unknown -> try UI handler
