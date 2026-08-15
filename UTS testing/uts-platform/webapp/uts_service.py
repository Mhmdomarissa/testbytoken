"""Bridge the web control plane to the existing UTS scanner and runner."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

from flask import current_app

from automation.selenium_session import set_browser, shutdown_all
from run_automation_only import create_and_run, scan_modules_to_json
from webapp.job_control import (
    JobStopped,
    clear_stop,
    is_stop_requested,
    set_active_job,
)
from webapp.models import (
    BusinessFlow,
    Execution,
    Module,
    Page,
    Project,
    ScanHistory,
    TestCase,
    UIObject,
    db,
)


ENGINE_LOCK = threading.Lock()


def _make_step_progress_callback(execution_id: int | None):
    """Update Execution.current_step so the web UI shows the live step."""
    if not execution_id:
        return None

    def _on_progress(message: str) -> None:
        try:
            execution = db.session.get(Execution, execution_id)
            if not execution:
                return
            # Prefer short "TC: Step x/y: Action..." text from step_banner
            clean = message.strip()
            if "\n" in clean:
                lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
                # Rebuild a short line from banner fields when possible
                short_parts = []
                for ln in lines:
                    if "NOW EXECUTING" in ln or ln.startswith("=="):
                        continue
                    if "|" in ln:
                        short_parts.append(ln.split("|", 1)[-1].strip())
                clean = " · ".join(short_parts[:4]) if short_parts else lines[0]
            if clean.startswith("[") and "]" in clean:
                clean = clean.split("]", 1)[-1].strip()
                if clean.startswith(">>>"):
                    clean = clean[3:].strip()
            execution.current_step = clean[:500]
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()

    return _on_progress


def _root() -> Path:
    return Path(current_app.config["UTS_ROOT"])


def _project_input(project: Project) -> dict:
    return {
        "url": project.application_url,
        "username": project.app_username or "",
        "password": project.app_password or "",
        "app_name": project.name,
        "role": project.app_role or "",
        "module": "",
        "ai_mode": True,
        "run_automation": False,
        "logout_after_each_test": True,
        "show_execution_log_in_report": False,
    }


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _archive(project_id: int, history_id: int) -> Path:
    root = _root()
    destination = root / "web-data" / "projects" / str(project_id) / f"run-{history_id}"
    destination.mkdir(parents=True, exist_ok=True)
    for folder in ("generated", "reports", "alm-output", "xpedite-output"):
        source = root / folder
        target = destination / folder
        if source.exists():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
    return destination


def run_module_scan(project_id: int, history_id: int) -> None:
    project = db.session.get(Project, project_id)
    history = db.session.get(ScanHistory, history_id)
    if not project or not history:
        return
    history.status = "RUNNING"
    history.started_at = datetime.utcnow()
    history.message = "Launching browser and discovering modules"
    project.status = "SCANNING"
    db.session.commit()

    clear_stop()
    set_active_job(project_id=project.id, history_id=history.id)

    try:
        with ENGINE_LOCK:
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            set_browser(project.browser)
            modules = scan_modules_to_json(_project_input(project))
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            archive = _archive(project.id, history.id)
        persist_modules(project, modules)
        history.module_count = len(modules)
        history.artifact_path = str(archive)
        history.status = "COMPLETED"
        history.message = f"Discovered {len(modules)} module(s). Select modules to continue."
        project.status = "SCANNED"
    except JobStopped as exc:
        history.status = "STOPPED"
        history.message = str(exc) or "Stopped by user"
        project.status = "STOPPED"
    except Exception as exc:
        history.status = "FAILED"
        history.message = str(exc)
        project.status = "SCAN_FAILED"
    finally:
        history.completed_at = datetime.utcnow()
        db.session.commit()
        set_active_job()
        clear_stop()
        shutdown_all()


def run_generation(
    project_id: int,
    history_id: int,
    selected_modules: list[str],
    execute: bool = False,
    execution_id: int | None = None,
) -> None:
    project = db.session.get(Project, project_id)
    history = db.session.get(ScanHistory, history_id)
    execution = db.session.get(Execution, execution_id) if execution_id else None
    if not project or not history:
        return

    history.status = "RUNNING"
    history.started_at = datetime.utcnow()
    history.message = "Discovering selected module flows and UI objects"
    project.status = "EXECUTING" if execute else "GENERATING"
    if execution:
        execution.status = "RUNNING"
        execution.started_at = datetime.utcnow()
        execution.current_step = "Launching application"
    db.session.commit()

    clear_stop()
    set_active_job(
        project_id=project.id,
        execution_id=execution.id if execution else None,
        history_id=history.id,
    )

    try:
        inp = _project_input(project)
        inp["module"] = "#".join(selected_modules)
        inp["run_automation"] = execute
        selected_test_case_keys = None
        if execution and execution.test_case_ids:
            selected_test_case_keys = [
                case.external_key
                for case_id in execution.test_case_ids
                if (case := db.session.get(TestCase, int(case_id))) is not None
                and case.project_id == project.id
            ]
        with ENGINE_LOCK:
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            set_browser(project.browser)
            exit_code = create_and_run(
                inp,
                selected_modules,
                run_tests=execute,
                open_outputs=False,
                selected_test_case_ids=selected_test_case_keys,
                on_step_progress=_make_step_progress_callback(execution.id if execution else None),
            )
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            archive = _archive(project.id, history.id)

        flow = _read_json(_root() / "generated" / "discovered-flow.json")
        page_map = _read_json(_root() / "generated" / "page-map.json")
        persist_discovery(project, flow, page_map)

        history.module_count = len(selected_modules)
        history.page_count = len(page_map.get("pages") or [])
        history.object_count = UIObject.query.filter_by(project_id=project.id).count()
        history.artifact_path = str(archive)
        history.status = "COMPLETED" if exit_code == 0 else "FAILED"
        history.message = (
            f"Generated {len(flow.get('scenarios') or [])} test case(s), "
            f"{history.page_count} page(s), and {history.object_count} object(s)."
        )
        project.status = "READY" if exit_code == 0 else "EXECUTION_FAILED"

        if execution:
            _complete_execution(execution, exit_code, archive)
    except JobStopped as exc:
        history.status = "STOPPED"
        history.message = str(exc) or "Stopped by user"
        project.status = "STOPPED"
        if execution:
            execution.status = "STOPPED"
            execution.message = "Stopped by user"
            execution.current_step = "Stopped by user"
            execution.completed_at = datetime.utcnow()
    except Exception as exc:
        history.status = "FAILED"
        history.message = str(exc)
        project.status = "FAILED"
        if execution:
            execution.status = "FAILED"
            execution.message = str(exc)
            execution.completed_at = datetime.utcnow()
    finally:
        history.completed_at = datetime.utcnow()
        db.session.commit()
        set_active_job()
        clear_stop()
        shutdown_all()


def run_full_pipeline(
    project_id: int,
    history_id: int,
    selected_modules: list[str],
    execution_id: int,
) -> None:
    """Scan (if needed) → generate positive/negative TCs → run automation → report."""
    project = db.session.get(Project, project_id)
    history = db.session.get(ScanHistory, history_id)
    execution = db.session.get(Execution, execution_id)
    if not project or not history or not execution:
        return

    history.status = "RUNNING"
    history.started_at = datetime.utcnow()
    history.message = "Starting full pipeline"
    execution.status = "RUNNING"
    execution.started_at = datetime.utcnow()
    execution.current_step = "Checking modules"
    project.status = "EXECUTING"
    db.session.commit()

    clear_stop()
    set_active_job(project_id=project.id, execution_id=execution.id, history_id=history.id)

    try:
        module_count = Module.query.filter_by(project_id=project.id).count()
        if module_count == 0:
            raise_if_pipeline_stopped(execution)
            execution.current_step = "Scanning application modules"
            db.session.commit()
            with ENGINE_LOCK:
                if is_stop_requested():
                    raise JobStopped("Stopped by user")
                set_browser(project.browser)
                modules = scan_modules_to_json(_project_input(project))
                if is_stop_requested():
                    raise JobStopped("Stopped by user")
            persist_modules(project, modules)
            history.module_count = len(modules)
            if not selected_modules and modules:
                selected_modules = [m.get("name") or m.get("id") for m in modules if m.get("name")]

        if not selected_modules:
            raise ValueError("No modules selected. Run a scan and select at least one module.")

        raise_if_pipeline_stopped(execution)
        execution.current_step = "Generating test cases and running automation"
        db.session.commit()

        inp = _project_input(project)
        inp["module"] = "#".join(selected_modules)
        inp["run_automation"] = True

        with ENGINE_LOCK:
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            set_browser(project.browser)
            exit_code = create_and_run(
                inp,
                selected_modules,
                run_tests=True,
                open_outputs=False,
                on_step_progress=_make_step_progress_callback(execution.id),
            )
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            archive = _archive(project.id, history.id)

        flow = _read_json(_root() / "generated" / "discovered-flow.json")
        page_map = _read_json(_root() / "generated" / "page-map.json")
        persist_discovery(project, flow, page_map)

        scenario_count = len(flow.get("scenarios") or [])
        history.module_count = len(selected_modules)
        history.page_count = len(page_map.get("pages") or [])
        history.object_count = UIObject.query.filter_by(project_id=project.id).count()
        history.artifact_path = str(archive)
        history.status = "COMPLETED" if exit_code == 0 else "FAILED"
        history.message = (
            f"Pipeline complete: {scenario_count} test case(s), "
            f"automation {'passed' if exit_code == 0 else 'finished with failures'}."
        )
        project.status = "READY" if exit_code == 0 else "EXECUTION_FAILED"
        _complete_execution(execution, exit_code, archive)
        execution.current_step = "Report ready"
    except JobStopped as exc:
        history.status = "STOPPED"
        history.message = str(exc) or "Stopped by user"
        project.status = "STOPPED"
        execution.status = "STOPPED"
        execution.message = "Stopped by user"
        execution.current_step = "Stopped by user"
        execution.completed_at = datetime.utcnow()
    except Exception as exc:
        history.status = "FAILED"
        history.message = str(exc)
        project.status = "FAILED"
        execution.status = "FAILED"
        execution.message = str(exc)
        execution.completed_at = datetime.utcnow()
    finally:
        history.completed_at = datetime.utcnow()
        db.session.commit()
        set_active_job()
        clear_stop()
        shutdown_all()


def raise_if_pipeline_stopped(execution: Execution) -> None:
    if is_stop_requested():
        execution.current_step = "Stopped by user"
        db.session.commit()
        raise JobStopped("Stopped by user")


def stop_running_jobs(project_id: int) -> dict:
    """Request stop, close browser, and mark active jobs as STOPPED."""
    from webapp.job_control import request_stop

    request_stop()
    try:
        shutdown_all()
    except Exception:  # noqa: BLE001
        pass

    now = datetime.utcnow()
    stopped = {"scans": 0, "executions": 0}

    for history in ScanHistory.query.filter(
        ScanHistory.project_id == project_id,
        ScanHistory.status.in_(("QUEUED", "RUNNING")),
    ).all():
        history.status = "STOPPED"
        history.message = "Stopped by user"
        history.completed_at = now
        stopped["scans"] += 1

    for execution in Execution.query.filter(
        Execution.project_id == project_id,
        Execution.status.in_(("QUEUED", "RUNNING")),
    ).all():
        execution.status = "STOPPED"
        execution.message = "Stopped by user"
        execution.current_step = "Stopped by user"
        execution.completed_at = now
        stopped["executions"] += 1

    project = db.session.get(Project, project_id)
    if project and project.status in {
        "SCANNING",
        "GENERATING",
        "EXECUTING",
    }:
        project.status = "STOPPED"

    db.session.commit()
    return stopped


def persist_modules(project: Project, modules: list[dict]) -> None:
    seen: set[str] = set()
    for item in modules:
        key = str(item.get("id") or item.get("name") or "").strip()
        if not key:
            continue
        seen.add(key)
        module = Module.query.filter_by(project_id=project.id, external_key=key).first()
        if not module:
            module = Module(project_id=project.id, external_key=key, name=item.get("name") or key)
            db.session.add(module)
        module.name = item.get("name") or key
        module.last_seen_at = datetime.utcnow()
    db.session.commit()


def persist_discovery(project: Project, flow: dict, page_map: dict) -> None:
    modules_payload = flow.get("modules") or page_map.get("modules") or []
    persist_modules(project, modules_payload)
    module_by_name = {
        module.name.lower(): module
        for module in Module.query.filter_by(project_id=project.id).all()
    }

    pages_by_path: dict[str, Page] = {}
    for item in page_map.get("pages") or []:
        module_name = str(item.get("module") or "Core")
        module = module_by_name.get(module_name.lower())
        if not module:
            module = Module(project_id=project.id, external_key=_slug(module_name), name=module_name)
            db.session.add(module)
            db.session.flush()
            module_by_name[module_name.lower()] = module

        path = str(item.get("path") or item.get("sub_page") or module_name)
        page = Page.query.filter_by(module_id=module.id, path=path).first()
        if not page:
            page = Page(module_id=module.id, name=str(item.get("sub_page") or module_name), path=path)
            db.session.add(page)
        page.url = str(item.get("url") or "")
        page.page_type = str(item.get("page_type") or "unknown")
        page.parent_path = path.rsplit(">", 1)[0].strip() if ">" in path else ""
        page.summary = str(item.get("summary") or "")
        page.last_seen_at = datetime.utcnow()
        db.session.flush()
        pages_by_path[path] = page

        for field in item.get("fields") or []:
            _upsert_object(
                project,
                page,
                str(field.get("label") or "Field"),
                str(field.get("type") or field.get("tag") or "input"),
                "",
                "",
                field,
            )
        for button in item.get("buttons") or []:
            _upsert_object(
                project,
                page,
                str(button.get("label") or "Button"),
                "button",
                "",
                "",
                button,
            )

    locators = flow.get("locators") or {}
    default_page = next(iter(pages_by_path.values()), None)
    for key, locator in locators.items():
        if not isinstance(locator, dict):
            continue
        name = _object_name_from_key(key)
        _upsert_object(
            project,
            default_page,
            name,
            _infer_object_type(key, name),
            str(locator.get("by") or ""),
            str(locator.get("value") or ""),
            locator,
            repository_key=key,
        )

    for scenario in flow.get("scenarios") or []:
        module_name = str(scenario.get("module") or "Core")
        module = module_by_name.get(module_name.lower())
        if not module:
            module = Module(project_id=project.id, external_key=_slug(module_name), name=module_name)
            db.session.add(module)
            db.session.flush()
            module_by_name[module_name.lower()] = module
        scenario_key = str(scenario.get("id") or _slug(scenario.get("title") or "flow"))
        business_flow = BusinessFlow.query.filter_by(
            module_id=module.id, external_key=scenario_key
        ).first()
        if not business_flow:
            business_flow = BusinessFlow(
                module_id=module.id,
                external_key=scenario_key,
                name=str(scenario.get("title") or scenario_key),
            )
            db.session.add(business_flow)
        steps = list(scenario.get("steps") or [])
        business_flow.actions = steps
        business_flow.navigation_path = " > ".join(
            str(step.get("object_name") or "")
            for step in steps
            if str(step.get("action") or "").lower() in {"navigate", "performclick"}
        )
        business_flow.last_seen_at = datetime.utcnow()
        db.session.flush()

        test_case = TestCase.query.filter_by(
            project_id=project.id, external_key=scenario_key
        ).first()
        if not test_case:
            test_case = TestCase(
                project_id=project.id,
                module_id=module.id,
                flow_id=business_flow.id,
                external_key=scenario_key,
                name=str(scenario.get("title") or scenario_key),
            )
            db.session.add(test_case)
        test_case.name = str(scenario.get("title") or scenario_key)
        test_case.test_type = str(scenario.get("type") or "automation")
        test_case.manual_steps = [
            {
                "step": step.get("step_no"),
                "action": step.get("action"),
                "object": step.get("object_name"),
                "expected": step.get("expected"),
            }
            for step in steps
        ]
        test_case.automation_steps = steps
        test_case.expected_result = str(steps[-1].get("expected") or "") if steps else ""

    db.session.commit()


def _upsert_object(
    project: Project,
    page: Page | None,
    name: str,
    object_type: str,
    locator_by: str,
    locator_value: str,
    attributes: dict,
    repository_key: str = "",
) -> None:
    fingerprint = hashlib.sha256(
        f"{name.lower()}|{object_type}|{locator_by}|{locator_value}".encode("utf-8")
    ).hexdigest()
    key = repository_key or fingerprint[:32]
    obj = UIObject.query.filter_by(project_id=project.id, repository_key=key).first()
    if not obj:
        # Duplicate detection across pages by fingerprint.
        obj = UIObject.query.filter_by(project_id=project.id, fingerprint=fingerprint).first()
    if not obj:
        obj = UIObject(
            project_id=project.id,
            page_id=page.id if page else None,
            repository_key=key,
            name=name,
            object_type=object_type,
            first_seen_at=datetime.utcnow(),
        )
        db.session.add(obj)
    elif obj.locator_value and locator_value and obj.locator_value != locator_value:
        obj.change_count += 1
        alternatives = list(obj.alternate_locators or [])
        alternatives.append({"by": obj.locator_by, "value": obj.locator_value})
        obj.alternate_locators = alternatives[-5:]

    obj.page_id = page.id if page else obj.page_id
    obj.name = name
    obj.object_type = object_type
    obj.locator_by = locator_by or obj.locator_by
    obj.locator_value = locator_value or obj.locator_value
    obj.attributes = attributes
    obj.fingerprint = fingerprint
    obj.stable_score = _stable_locator_score(locator_by, locator_value)
    obj.last_seen_at = datetime.utcnow()


def _stable_locator_score(by: str, value: str) -> int:
    by = (by or "").lower()
    value = value or ""
    score = {"id": 95, "name": 90, "css": 75, "xpath": 60}.get(by, 40)
    if any(token in value.lower() for token in ("contains(", "nth-", "[1]", "[2]")):
        score -= 20
    if len(value) > 180:
        score -= 15
    return max(0, min(100, score))


def _complete_execution(execution: Execution, exit_code: int, archive: Path) -> None:
    report = _root() / "reports" / "latest-e2e-report.html"
    execution.status = "PASSED" if exit_code == 0 else "FAILED"
    execution.message = "Automation completed" if exit_code == 0 else "Automation failed"
    execution.report_path = str(archive / "reports" / report.name) if report.exists() else ""
    execution.completed_at = datetime.utcnow()
    results = sorted((_root() / "reports").glob("e2e-results-*.json"))
    if results:
        payload = _read_json(results[-1])
        summary = payload.get("summary") or {}
        automation = payload.get("automation") or payload.get("results") or []
        if isinstance(automation, list):
            execution.total = len(automation)
            execution.passed = sum(1 for item in automation if item.get("status") == "PASS")
            execution.failed = execution.total - execution.passed
        elif summary:
            execution.total = summary.get("total", execution.total)
            execution.passed = summary.get("auto_pass", execution.passed)
            execution.failed = summary.get("auto_fail", execution.failed)
    elif exit_code == 0:
        execution.passed = execution.total


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def _object_name_from_key(key: str) -> str:
    words = key.replace("-", "_").split("_")
    if words and words[0] in {"el", "nav", "mod", "field", "btn"}:
        words = words[1:]
    return " ".join(word for word in words if not word.isdigit()).strip().title() or key


def _infer_object_type(key: str, name: str) -> str:
    text = f"{key} {name}".lower()
    for object_type in (
        "button",
        "checkbox",
        "radio",
        "dropdown",
        "select",
        "table",
        "link",
        "menu",
        "image",
        "frame",
        "label",
        "password",
        "username",
        "field",
    ):
        if object_type in text:
            return "textbox" if object_type in {"field", "password", "username"} else object_type
    return "element"


def _parse_manual_steps(raw_text: str) -> list[dict]:
    """Parse lines: Action | Object | Value | Expected | locator_by | locator_value"""
    steps: list[dict] = []
    for index, line in enumerate((raw_text or "").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        while len(parts) < 6:
            parts.append("")
        action, obj, value, expected, locator_by, locator_value = parts[:6]
        if not action:
            continue
        steps.append(
            {
                "step_no": index,
                "action": action,
                "object_name": obj or action,
                "input_value": value,
                "expected": expected,
                "locator_by": locator_by,
                "locator_value": locator_value,
            }
        )
    return steps


def create_manual_test_case(
    project: Project,
    *,
    name: str,
    test_type: str = "automation",
    steps_text: str = "",
    module_name: str = "Manual",
) -> TestCase:
    """Create a user-authored test case under a Manual module."""
    module = Module.query.filter_by(project_id=project.id, name=module_name).first()
    if not module:
        module = Module(
            project_id=project.id,
            external_key=f"mod-{module_name.lower().replace(' ', '-')}",
            name=module_name,
            selected=True,
        )
        db.session.add(module)
        db.session.flush()

    steps = _parse_manual_steps(steps_text)
    if not steps:
        steps = [
            {
                "step_no": 1,
                "action": "Navigate",
                "object_name": "Application URL",
                "input_value": project.application_url,
                "expected": "Application page loads",
                "locator_by": "",
                "locator_value": "",
            }
        ]

    stamp = datetime.utcnow().strftime("%H%M%S")
    external_key = f"TC_MANUAL_{stamp}"
    case = TestCase(
        project_id=project.id,
        module_id=module.id,
        external_key=external_key,
        name=name.strip() or external_key,
        test_type=(test_type or "automation").strip().lower() or "automation",
        manual_steps=steps,
        automation_steps=steps,
        expected_result=str(steps[-1].get("expected") or ""),
        enabled=True,
    )
    db.session.add(case)
    db.session.commit()
    return case


def scenarios_from_test_cases(cases: list[TestCase]) -> list:
    from dynamic.discovery import ScenarioDef, StepDef

    scenarios = []
    for case in cases:
        raw_steps = case.automation_steps or case.manual_steps or []
        steps = []
        for index, raw in enumerate(raw_steps, start=1):
            if not isinstance(raw, dict):
                continue
            steps.append(
                StepDef(
                    step_no=int(raw.get("step_no") or index),
                    action=str(raw.get("action") or "Verify"),
                    object_name=str(raw.get("object_name") or ""),
                    input_value=str(raw.get("input_value") or ""),
                    locator_by=str(raw.get("locator_by") or ""),
                    locator_value=str(raw.get("locator_value") or ""),
                    expected=str(raw.get("expected") or ""),
                )
            )
        module_name = ""
        if case.module_id:
            module = db.session.get(Module, case.module_id)
            module_name = module.name if module else ""
        scenarios.append(
            ScenarioDef(
                id=case.external_key,
                type=case.test_type or "automation",
                title=case.name,
                steps=steps,
                module=module_name,
            )
        )
    return scenarios


def run_stored_test_cases(
    project_id: int,
    history_id: int,
    execution_id: int | None,
    test_case_ids: list[int],
) -> None:
    """Run selected DB test cases (AI-generated or manually created) in the browser."""
    import time

    from automation.selenium_session import get_driver, start_browser
    from dynamic.automation_runner import run_all_automation
    from dynamic.discovery import DiscoveryResult
    from report_generator import write_html_report
    from automation.base import ExecutionLogger

    project = db.session.get(Project, project_id)
    history = db.session.get(ScanHistory, history_id)
    execution = db.session.get(Execution, execution_id) if execution_id else None
    if not project or not history:
        return

    cases = (
        TestCase.query.filter(
            TestCase.project_id == project.id,
            TestCase.id.in_(test_case_ids),
            TestCase.enabled.is_(True),
        )
        .order_by(TestCase.id)
        .all()
    )
    history.status = "RUNNING"
    history.started_at = datetime.utcnow()
    history.message = f"Running {len(cases)} stored test case(s)"
    project.status = "RUNNING"
    if execution:
        execution.status = "RUNNING"
        execution.started_at = datetime.utcnow()
        execution.current_step = "Opening browser for stored test cases"
        execution.total = len(cases)
    db.session.commit()

    clear_stop()
    set_active_job(
        project_id=project.id,
        execution_id=execution.id if execution else None,
        history_id=history.id,
    )

    started = time.perf_counter()
    try:
        if not cases:
            raise RuntimeError("No enabled test cases selected")

        scenarios = scenarios_from_test_cases(cases)
        discovery = DiscoveryResult(
            url=project.application_url,
            username=project.app_username or "",
            app_name=project.name,
            page_title=project.name,
            discovered_at=datetime.utcnow().isoformat(timespec="seconds"),
            login_url=project.application_url,
            post_login_url=project.application_url,
            locators={},
            scenarios=scenarios,
        )

        with ENGINE_LOCK:
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            set_browser(project.browser or "chrome")
            start_browser(project.application_url)
            logger = ExecutionLogger("stored-tc-run")
            if execution:
                logger.on_progress = _make_step_progress_callback(execution.id)
            results = run_all_automation(
                discovery,
                project.app_password or "",
                logger,
                logout_after_each=True,
                continue_on_failure=True,
                role_hint=project.app_role or "",
                run_test_cases_only=[c.external_key for c in cases],
            )
            if is_stop_requested():
                raise JobStopped("Stopped by user")

            total_ms = (time.perf_counter() - started) * 1000
            report_path = write_html_report(
                automation_results=results,
                manual_scenarios=[],
                execution_log=logger.content,
                suite_name=f"{project.name} — stored cases",
                environment=project.application_url,
                total_duration_ms=total_ms,
                show_execution_log=False,
            )
            archive = _archive(project.id, history.id)
            archived_report = archive / "reports" / report_path.name
            if not archived_report.is_file():
                archived_report = archive / "reports" / "latest-e2e-report.html"
            passed = sum(1 for r in results if r.status == "PASS")
            failed = sum(1 for r in results if r.status == "FAIL")

        history.status = "COMPLETED" if failed == 0 else "FAILED"
        history.message = f"Stored run: {passed} passed, {failed} failed"
        history.artifact_path = str(archive)
        project.status = "READY" if failed == 0 else "EXECUTION_FAILED"
        if execution:
            execution.status = history.status
            execution.passed = passed
            execution.failed = failed
            execution.total = len(results)
            execution.report_path = str(archived_report if archived_report.is_file() else report_path)
            execution.message = history.message
            execution.current_step = "Completed"
            execution.completed_at = datetime.utcnow()
    except JobStopped as exc:
        history.status = "STOPPED"
        history.message = str(exc) or "Stopped by user"
        project.status = "STOPPED"
        if execution:
            execution.status = "STOPPED"
            execution.message = "Stopped by user"
            execution.current_step = "Stopped by user"
            execution.completed_at = datetime.utcnow()
    except Exception as exc:  # noqa: BLE001
        history.status = "FAILED"
        history.message = str(exc)
        project.status = "FAILED"
        if execution:
            execution.status = "FAILED"
            execution.message = str(exc)
            execution.completed_at = datetime.utcnow()
    finally:
        history.completed_at = datetime.utcnow()
        db.session.commit()
        set_active_job()
        clear_stop()
        shutdown_all()

