"""
UTS Worker Agent — runs on each user's machine (B / C / D).

Keep this process running while you use the central UTS web platform.
When you click Scan / Run in the browser, this agent opens Chrome locally
and sends results back to the server.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# services/engine/, two levels above this file (uts_engine/worker/) — kept on
# sys.path so this still works whether invoked as `-m` or as a bare script.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

TOKEN_FILE = ROOT / "web-data" / "worker-token.json"


def _http_json(method: str, url: str, payload: dict | None = None, token: str = "") -> dict:
    data = None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(req, timeout=120) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
        except Exception:  # noqa: BLE001
            parsed = {"error": detail or str(exc)}
        raise RuntimeError(parsed.get("error") or str(exc)) from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach UTS server: {exc.reason}") from exc


def _read_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _collect_artifacts() -> dict:
    artifacts: dict = {}
    modules = _read_json(ROOT / "generated" / "modules.json")
    if modules is not None:
        artifacts["modules"] = modules
    flow = _read_json(ROOT / "generated" / "discovered-flow.json")
    if flow is not None:
        artifacts["discovered_flow"] = flow
    page_map = _read_json(ROOT / "generated" / "page-map.json")
    if page_map is not None:
        artifacts["page_map"] = page_map
    report = ROOT / "reports" / "latest-e2e-report.html"
    if report.is_file():
        artifacts["report_html"] = report.read_text(encoding="utf-8", errors="replace")
    return artifacts


def _should_stop(server: str, token: str, job_id: int) -> bool:
    try:
        data = _http_json("GET", f"{server}/api/worker/jobs/{job_id}/status", token=token)
        return bool(data.get("stop_requested"))
    except Exception:  # noqa: BLE001
        return False


def _progress(server: str, token: str, job_id: int, message: str) -> bool:
    data = _http_json(
        "POST",
        f"{server}/api/worker/jobs/{job_id}/progress",
        {"message": message, "status": "RUNNING"},
        token=token,
    )
    return bool(data.get("stop_requested"))


def _run_job(job: dict, server: str, token: str) -> tuple[str, str, int]:
    from uts_engine.automation.selenium_session import set_browser, shutdown_all, start_browser
    from uts_engine.cli import create_and_run, scan_modules_to_json
    from uts_engine.job_control import JobStopped, clear_stop, is_stop_requested, request_stop

    job_id = int(job["id"])
    payload = job.get("payload") or {}
    job_type = (job.get("job_type") or payload.get("job_type") or "MODULES").upper()
    project = payload.get("project") or {}
    inp = dict(payload.get("input") or {})
    selected = list(payload.get("selected_modules") or [])
    execute = bool(payload.get("execute"))
    browser = project.get("browser") or "chrome"
    stored = list(payload.get("stored_scenarios") or [])

    clear_stop()
    set_browser(browser)

    def stop_watcher():
        while True:
            if _should_stop(server, token, job_id):
                request_stop()
                return
            time.sleep(2)

    import threading

    watcher = threading.Thread(target=stop_watcher, daemon=True)
    watcher.start()

    try:
        if _progress(server, token, job_id, f"Opening browser on this machine ({platform.node()})"):
            raise JobStopped("Stopped by user")

        if job_type == "MODULES":
            modules = scan_modules_to_json(inp)
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            return "COMPLETED", f"Discovered {len(modules)} module(s) on this machine", 0

        if job_type == "STORED_EXECUTION" and stored:
            from datetime import datetime

            from uts_engine.automation.base import ExecutionLogger
            from uts_engine.discovery.automation_runner import run_all_automation
            from uts_engine.discovery.discovery import DiscoveryResult, ScenarioDef, StepDef
            from uts_engine.exporters.report_generator import write_html_report

            scenarios = []
            for raw in stored:
                steps = [
                    StepDef(
                        step_no=int(st.get("step_no") or i),
                        action=str(st.get("action") or "Verify"),
                        object_name=str(st.get("object_name") or ""),
                        input_value=str(st.get("input_value") or ""),
                        locator_by=str(st.get("locator_by") or ""),
                        locator_value=str(st.get("locator_value") or ""),
                        expected=str(st.get("expected") or ""),
                    )
                    for i, st in enumerate(raw.get("steps") or [], start=1)
                ]
                scenarios.append(
                    ScenarioDef(
                        id=str(raw.get("id") or f"TC_{len(scenarios)+1}"),
                        type=str(raw.get("type") or "automation"),
                        title=str(raw.get("title") or raw.get("id") or "Manual case"),
                        steps=steps,
                        module=str(raw.get("module") or "Manual"),
                    )
                )
            url = project.get("application_url") or inp.get("url") or ""
            discovery = DiscoveryResult(
                url=url,
                username=project.get("app_username") or inp.get("username") or "",
                app_name=project.get("name") or "UTS",
                page_title=project.get("name") or "UTS",
                discovered_at=datetime.utcnow().isoformat(timespec="seconds"),
                login_url=url,
                post_login_url=url,
                scenarios=scenarios,
            )
            if _progress(server, token, job_id, f"Running {len(scenarios)} stored test case(s)"):
                raise JobStopped("Stopped by user")
            start_browser(url)
            logger = ExecutionLogger("worker-stored-tc")
            results = run_all_automation(
                discovery,
                project.get("app_password") or inp.get("password") or "",
                logger,
                logout_after_each=True,
                continue_on_failure=True,
                role_hint=project.get("app_role") or "",
                run_test_cases_only=[s.id for s in scenarios],
            )
            if is_stop_requested():
                raise JobStopped("Stopped by user")
            write_html_report(
                automation_results=results,
                manual_scenarios=[],
                execution_log=logger.content,
                suite_name=f"{project.get('name') or 'UTS'} — stored cases",
                environment=url,
                total_duration_ms=0,
                show_execution_log=False,
            )
            failed = sum(1 for r in results if r.status == "FAIL")
            exit_code = 0 if failed == 0 else 1
            status = "COMPLETED" if exit_code == 0 else "FAILED"
            return status, f"Stored cases finished ({len(results)} run, {failed} failed)", exit_code

        if not selected:
            raise ValueError("No modules selected for this job")

        if _progress(server, token, job_id, f"Running {job_type} for: {', '.join(selected)}"):
            raise JobStopped("Stopped by user")

        run_tests = execute or job_type in {"EXECUTION", "PIPELINE"}
        if job_type == "PIPELINE":
            # Ensure modules exist first when needed.
            from uts_engine.discovery.module_selector import modules_catalog_exists

            if not modules_catalog_exists():
                scan_modules_to_json(inp)
        exit_code = create_and_run(
            inp,
            selected,
            run_tests=run_tests,
            open_outputs=False,
        )
        if is_stop_requested():
            raise JobStopped("Stopped by user")
        status = "COMPLETED" if exit_code == 0 else "FAILED"
        return status, f"{job_type} finished on this machine (exit {exit_code})", exit_code
    except JobStopped as exc:
        return "STOPPED", str(exc) or "Stopped by user", 1
    except Exception as exc:  # noqa: BLE001
        return "FAILED", str(exc), 1
    finally:
        shutdown_all()
        clear_stop()


def register(server: str, username: str, password: str, browser: str) -> dict:
    machine = platform.node() or socket.gethostname() or "worker"
    data = _http_json(
        "POST",
        f"{server}/api/worker/register",
        {
            "username": username,
            "password": password,
            "machine_name": machine,
            "platform": platform.system().lower(),
            "browser": browser,
        },
    )
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps(
            {
                "server": server,
                "token": data["token"],
                "worker_id": data.get("worker_id"),
                "username": username,
                "machine_name": machine,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Do not auto-install Startup shortcuts — only when user runs Installer intentionally.
    return data


def load_saved_token(server: str) -> str:
    if not TOKEN_FILE.is_file():
        return ""
    try:
        saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        if saved.get("server") == server and saved.get("token"):
            return saved["token"]
    except Exception:  # noqa: BLE001
        return ""
    return ""


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        load_dotenv(ROOT / "worker.env")
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(description="UTS Worker Agent for this machine")
    parser.add_argument(
        "--server",
        default=os.getenv("UTS_SERVER_URL", "http://127.0.0.1:5050"),
        help="Central UTS URL, e.g. http://192.168.1.94:5050",
    )
    parser.add_argument("--username", default=os.getenv("UTS_WORKER_USERNAME", "") or os.getenv("UTS_ADMIN_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("UTS_WORKER_PASSWORD", "") or os.getenv("UTS_ADMIN_PASSWORD", ""))
    parser.add_argument("--browser", default=os.getenv("UTS_WORKER_BROWSER", "chrome"))
    parser.add_argument("--poll", type=float, default=3.0, help="Seconds between job polls")
    args = parser.parse_args()

    server = args.server.rstrip("/")
    print()
    print("=" * 64)
    print("  UTS WORKER AGENT")
    print(f"  Server : {server}")
    print(f"  Machine: {platform.node()} ({platform.system()})")
    print("  Browser opens on THIS machine when you Scan/Run in UTS.")
    print("  Keep this window open. Ctrl+C to stop.")
    print("=" * 64)
    print()

    token = load_saved_token(server)
    if not token:
        username = args.username or input("UTS username: ").strip()
        password = args.password or input("UTS password: ")
        try:
            result = register(server, username, password, args.browser)
        except Exception as exc:  # noqa: BLE001
            print(f"Register failed: {exc}")
            return 1
        token = result["token"]
        print(f"Registered as worker for user '{result.get('username')}'.")
    else:
        print("Using saved worker token.")
        # Refresh registration if credentials are available (keeps auto-start healthy)
        if args.username and args.password:
            try:
                result = register(server, args.username, args.password, args.browser)
                token = result["token"]
                print(f"Re-registered as worker for user '{result.get('username')}'.")
            except Exception as exc:  # noqa: BLE001
                print(f"Token refresh skipped: {exc}")
                print("Continuing with saved token.")

    print("Waiting for jobs…")
    while True:
        try:
            _http_json("POST", f"{server}/api/worker/heartbeat", {}, token=token)
            nxt = _http_json("GET", f"{server}/api/worker/next-job", token=token)
            job = nxt.get("job")
            if job:
                print(f"\n>>> Job #{job['id']} ({job.get('job_type')}) — opening browser here…")
                status, message, exit_code = _run_job(job, server, token)
                artifacts = _collect_artifacts()
                _http_json(
                    "POST",
                    f"{server}/api/worker/jobs/{job['id']}/complete",
                    {
                        "status": status,
                        "message": message,
                        "exit_code": exit_code,
                        "artifacts": artifacts,
                    },
                    token=token,
                )
                print(f"<<< Job #{job['id']} => {status}: {message}\n")
            else:
                time.sleep(args.poll)
        except KeyboardInterrupt:
            print("\nWorker stopped.")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] {exc}")
            time.sleep(max(args.poll, 5))


if __name__ == "__main__":
    raise SystemExit(main())
