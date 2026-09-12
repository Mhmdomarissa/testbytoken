"""engine_host.py — one long-lived UTS engine per user.

This is the per-user mini server: a process today, a container later. It boots,
immediately pre-launches Chrome so that when the customer hits enter the run
costs a navigation rather than a browser start, and then serves commands for as
long as that user's session lasts.

Protocol is JSON lines both ways, so the parent never has to parse engine prose:

  stdin   {"cmd": "warm"}
          {"cmd": "scan", "job": "j1", "url": ..., "interactive": true}
          {"cmd": "continue", "job": "j1"}     <- customer finished logging in
          {"cmd": "run",  "job": "j1", "modules": ["Timesheets"]}
          {"cmd": "shutdown"}

  stdout  {"type": "status", "state": "booting|ready|busy|warming|warm"}
          {"type": "log",    "line": "..."}          <- engine print() output
          {"type": "awaiting_login", "job": ..., "url": ...}
          {"type": "step",   "job": ..., "message": "..."}
          {"type": "result", "job": ..., "ok": true, "data": {...}}
          {"type": "error",  "job": ..., "message": "..."}

Commands are read on the main thread and jobs run on a worker thread, so a job
parked on the login handoff can still receive "continue".

Everything this process writes goes under UTS_WORKDIR (see workdir.py), so two
users' engines never touch each other's artifacts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

# services/engine/, one level above uts_engine/ — kept on sys.path so this still
# works whether invoked as `python -m uts_engine.host` or as a bare script.
ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

# How long the customer gets to complete an interactive login before we give up.
LOGIN_TIMEOUT_SECONDS = int(os.environ.get("UTS_LOGIN_TIMEOUT", "600"))

# The real stdout is the protocol channel. The engine's own print() output is
# rerouted through _LogStream below and re-emitted as structured log events, so
# the two can never interleave and corrupt a JSON line.
_PROTOCOL_OUT = sys.stdout
_EMIT_LOCK = threading.Lock()


def emit(event: dict) -> None:
    line = json.dumps(event, default=str, ensure_ascii=False)
    with _EMIT_LOCK:
        _PROTOCOL_OUT.write(line + "\n")
        _PROTOCOL_OUT.flush()


class _LogStream:
    """Turns the engine's existing print() output into live log events.

    The UTS engine narrates itself heavily ("Modules scanned: 12"). Rather than
    add progress plumbing to every code path, forward what it already prints.
    """

    def __init__(self) -> None:
        self._buf = ""

    def write(self, chunk: str) -> int:
        self._buf += chunk
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip()
            if line:
                emit({"type": "log", "line": line})
        return len(chunk)

    def flush(self) -> None:
        if self._buf.strip():
            emit({"type": "log", "line": self._buf.rstrip()})
        self._buf = ""

    def isatty(self) -> bool:
        return False


def _build_input(
    url: str,
    username: str,
    password: str,
    *,
    app_name: str = "",
    role: str = "",
    modules: list[str] | None = None,
    run_automation: bool = False,
    logout_after_each: bool = True,
) -> dict:
    """The engine's app-input dict, built in memory.

    Deliberately not read from config/app-input.json: that file ships with the
    engine and carries another application's defaults.
    """
    modules = modules or []
    return {
        "url": url,
        "username": username,
        "password": password,
        "app_name": app_name or url.split("//")[-1].split("/")[0],
        "role": role,
        "module": "#".join(modules),
        "selected_modules": modules,
        "description": "",
        # Offline rule-based planner. config/ai.json pins provider=offline and
        # ai_brain falls back to offline without a key, so no external AI is called.
        "ai_mode": True,
        "automation_only": True,
        "run_automation": run_automation,
        # Logging out between test cases assumes we can log back in, which needs
        # stored credentials. With a customer-supplied interactive session there
        # are none — the reset would sign us out and every later test would run
        # unauthenticated, after wasting ~25s hunting a logout button.
        "logout_after_each_test": logout_after_each,
        "show_execution_log_in_report": False,
        "show_steps_in_browser": False,
    }


BLANK_URLS = ("data:,", "about:blank", "chrome://newtab/", "")


def _real_url(driver, requested: str, *candidates: str | None) -> str:
    """Never let a blank tab be mistaken for the customer's application.

    A driver that was created but not navigated sits on ``data:,``. If that URL
    escapes into discovery, the whole suite gets generated and executed against
    an empty page — every locator misses and the run looks broken for reasons
    that have nothing to do with the app.
    """
    for candidate in (*candidates, getattr(driver, "current_url", "")):
        value = (candidate or "").strip()
        if value and value not in BLANK_URLS:
            return value
    return requested


def _latest_results(reports_dir: Path) -> dict | None:
    """Newest e2e-results-*.json — the per-step data the proof screen renders.

    The engine has always written this file; the UTS worker simply never
    uploaded it, which is why step-level history did not exist upstream.
    """
    if not reports_dir.is_dir():
        return None
    files = sorted(reports_dir.glob("e2e-results-*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None


class EngineHost:
    def __init__(self) -> None:
        self.warm_thread: threading.Thread | None = None
        self.job_thread: threading.Thread | None = None
        self.data_root: Path | None = None
        self.continue_event = threading.Event()
        self.current_job: str | None = None

    # --- lifecycle -----------------------------------------------------

    def boot(self) -> None:
        emit({"type": "status", "state": "booting", "pid": os.getpid()})
        from uts_engine.workdir import data_root

        self.data_root = data_root()
        emit(
            {
                "type": "status",
                "state": "ready",
                "workdir": str(self.data_root),
                "pid": os.getpid(),
            }
        )
        self.warm()

    def warm(self) -> None:
        """Pre-launch Chrome in the background; never blocks the command loop."""
        if self.warm_thread and self.warm_thread.is_alive():
            return
        if self.job_thread and self.job_thread.is_alive():
            # A job owns the browser. Warming alongside it races for the driver
            # singleton and can hand the job an un-navigated tab.
            return

        def _warm() -> None:
            try:
                from uts_engine.automation.selenium_session import warm_browser

                emit({"type": "status", "state": "warming"})
                warm_browser()
                emit({"type": "status", "state": "warm"})
            except Exception as exc:  # noqa: BLE001
                emit({"type": "status", "state": "warm_failed", "message": str(exc)})

        self.warm_thread = threading.Thread(target=_warm, daemon=True)
        self.warm_thread.start()

    # --- interactive login ---------------------------------------------

    def login_handoff(self, job: str, url: str) -> str:
        """Park the run while the customer signs in themselves.

        We drive the browser to the target and then stop. The customer completes
        whatever the app demands — password, OTP, 2FA, CAPTCHA, SSO — in that
        window. What we keep afterwards is the session, never the credentials,
        and nothing is captured or screenshotted while they are typing.
        """
        from uts_engine.automation.selenium_session import (
            capture_session,
            get_driver,
            has_session,
            set_session,
            start_browser,
        )
        from uts_engine.discovery.discovery import _find_password, _find_username

        start_browser(url)
        driver = get_driver()
        time.sleep(1.5)

        needs_login = bool(_find_username(driver) and _find_password(driver))
        if not needs_login:
            emit(
                {
                    "type": "log",
                    "line": "  Already authenticated — no login form on this page"
                    if has_session()
                    else "  No login form detected — continuing without authentication",
                }
            )
            return _real_url(driver, url)

        emit(
            {
                "type": "awaiting_login",
                "job": job,
                "url": driver.current_url,
                "message": (
                    "Sign in to your application in the browser window that just opened, "
                    "then continue. Your credentials are never sent to us."
                ),
                "timeout_seconds": LOGIN_TIMEOUT_SECONDS,
            }
        )

        self.continue_event.clear()
        stop_beat = threading.Event()

        def _keepalive() -> None:
            """Hold the chromedriver connection open while the human signs in.

            A real login takes minutes. Selenium keeps a pooled HTTP connection
            to chromedriver, and chromedriver closes idle ones — so an idle wait
            long enough to be useful gets the socket reset out from under us, and
            the first command after "continue" dies with a ConnectionResetError.
            Touching the driver periodically keeps it alive, and tells us if the
            customer closed the window.
            """
            while not stop_beat.wait(15):
                try:
                    _ = driver.current_url
                except Exception as exc:  # noqa: BLE001
                    emit(
                        {
                            "type": "log",
                            "line": f"  Lost the browser window during login: {exc}",
                        }
                    )
                    return

        beat = threading.Thread(target=_keepalive, daemon=True)
        beat.start()
        try:
            signalled = self.continue_event.wait(timeout=LOGIN_TIMEOUT_SECONDS)
        finally:
            stop_beat.set()

        if not signalled:
            raise TimeoutError(
                f"Timed out after {LOGIN_TIMEOUT_SECONDS}s waiting for the login to be completed"
            )

        # Even with the heartbeat, the first call after a long pause can land on
        # a stale connection. urllib3 discards it, so one retry gets a fresh one.
        try:
            bundle = capture_session(driver)
        except Exception:  # noqa: BLE001
            bundle = capture_session(driver)
        # Some apps hold auth entirely in storage (JWT) with no cookies at all,
        # so only treat it as a failure when we got nothing whatsoever.
        if not any(
            (bundle.get("cookies"), bundle.get("local_storage"), bundle.get("session_storage"))
        ):
            raise RuntimeError(
                "Signed-in session could not be read from the browser. If the window "
                "was closed or the app signed you out, start the scan again."
            )
        set_session(bundle)
        post_login_url = _real_url(driver, url, bundle.get("url"))
        emit(
            {
                "type": "login_captured",
                "job": job,
                "post_login_url": post_login_url,
                # Counts only — cookie values are never emitted or logged.
                "cookies": len(bundle.get("cookies") or []),
                "all_domains": bool(bundle.get("all_domains")),
            }
        )
        return post_login_url

    # --- jobs ----------------------------------------------------------

    def scan(self, job: str, cmd: dict) -> None:
        from uts_engine.cli import scan_modules_to_json

        url = cmd["url"]
        if cmd.get("interactive"):
            url = self.login_handoff(job, url) or url

        inp = _build_input(
            url,
            cmd.get("username", ""),
            cmd.get("password", ""),
            app_name=cmd.get("app_name", ""),
            role=cmd.get("role", ""),
        )
        modules = scan_modules_to_json(inp)
        normalised = []
        for entry in modules or []:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("module") or entry.get("key") or ""
                normalised.append(
                    {
                        "name": str(name),
                        "key": str(entry.get("key") or entry.get("id") or name),
                        "pages": entry.get("pages") or entry.get("page_count") or 0,
                        "url": entry.get("url") or "",
                    }
                )
            elif entry:
                normalised.append({"name": str(entry), "key": str(entry), "pages": 0, "url": ""})
        emit(
            {
                "type": "result",
                "job": job,
                "ok": True,
                "data": {
                    "modules": normalised,
                    "count": len(normalised),
                    "crawl_url": url,
                },
            }
        )
        # The customer is now reading the module list — put Chrome back up so
        # clicking Run is instant.
        self.warm()

    def inspect(self, job: str, cmd: dict) -> None:
        """Open one module and inventory what a user can actually do on that page.

        The scan tells you a module exists. This clicks into it and enumerates the
        real surface — tabs, links, action buttons, form fields, search boxes —
        each with the locator the runner would use.

        Nothing is clicked except the module's own navigation link: pressing
        arbitrary buttons on a customer's app could submit forms or write data.
        """
        from uts_engine.automation.selenium_session import get_driver, has_session, start_browser
        from uts_engine.discovery.discovery import (
            _best_locator,
            _find_action_buttons,
            _find_form_fields,
            _find_headings,
            _find_nav_links,
            _find_search_fields,
            _find_sub_nav_links,
        )

        module = (cmd.get("module") or "").strip()
        url = cmd["url"]
        # A module only exists behind the front door, so honour the same login
        # path as scan and run rather than inspecting the login page.
        if cmd.get("interactive") and not has_session():
            url = self.login_handoff(job, url) or url
        print(f"  INSPECT MODULE: {module or '(current page)'}")
        start_browser(url)
        driver = get_driver()
        time.sleep(1.5)

        opened = False
        if module:
            target = module.casefold()
            nav = _find_nav_links(driver, limit=40)
            exact = [(t, e) for t, e in nav if t.strip().casefold() == target]
            partial = [(t, e) for t, e in nav if target in t.strip().casefold()]
            for label, element in exact + partial:
                try:
                    element.click()
                    opened = True
                    print(f"  Opened '{label}'")
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"  Could not click '{label}': {exc}")
            if not opened:
                print(f"  '{module}' not found in navigation — inspecting current page")
            else:
                time.sleep(2)  # let the module page render

        def loc(element) -> dict:
            try:
                _key, by, value = _best_locator(element)
                return {"by": by, "value": value}
            except Exception:  # noqa: BLE001
                return {"by": "", "value": ""}

        inventory = {
            "module": module,
            "opened": opened,
            "url": driver.current_url,
            "title": driver.title or "",
            "headings": _find_headings(driver)[:8],
            "tabs": [
                {"label": t, **loc(e)} for t, e in _find_sub_nav_links(driver, module, limit=20)
            ],
            "links": [{"label": t, **loc(e)} for t, e in _find_nav_links(driver, limit=40)],
            "buttons": [{"label": t, **loc(e)} for t, e in _find_action_buttons(driver, limit=30)],
            "inputs": [
                {"label": lbl, "tag": tag, **loc(e)}
                for lbl, tag, e in _find_form_fields(driver, limit=30)
            ],
            "searches": [{"label": t, **loc(e)} for t, e in _find_search_fields(driver, limit=6)],
        }
        counts = {k: len(v) for k, v in inventory.items() if isinstance(v, list)}
        inventory["counts"] = counts
        print(
            "  Found: "
            + ", ".join(f"{n} {k}" for k, n in counts.items() if n)
            + (" — nothing actionable found" if not any(counts.values()) else "")
        )
        emit({"type": "result", "job": job, "ok": True, "data": inventory})
        self.warm()

    def run(self, job: str, cmd: dict) -> None:
        from uts_engine.automation.selenium_session import has_session, safe_logout_after_each
        from uts_engine.cli import create_and_run

        modules = [m for m in (cmd.get("modules") or []) if str(m).strip()]
        if not modules:
            raise ValueError("No modules selected to test")

        url = cmd["url"]
        if cmd.get("interactive") and not has_session():
            url = self.login_handoff(job, url) or url

        inp = _build_input(
            url,
            cmd.get("username", ""),
            cmd.get("password", ""),
            app_name=cmd.get("app_name", ""),
            role=cmd.get("role", ""),
            modules=modules,
            run_automation=True,
            logout_after_each=safe_logout_after_each(True),
        )

        def on_step(message: str) -> None:
            emit({"type": "step", "job": job, "message": message})

        exit_code = create_and_run(
            inp,
            modules,
            run_tests=True,
            open_outputs=False,
            on_step_progress=on_step,
        )

        reports = (self.data_root or ENGINE_ROOT) / "reports"
        results = _latest_results(reports)
        report_html = reports / "latest-e2e-report.html"
        emit(
            {
                "type": "result",
                "job": job,
                "ok": exit_code == 0,
                "data": {
                    "exit_code": exit_code,
                    "results": results,
                    "report_html": str(report_html) if report_html.is_file() else "",
                },
            }
        )
        self.warm()

    def _run_job(self, name: str, job: str, cmd: dict) -> None:
        emit({"type": "status", "state": "busy", "job": job, "phase": name})
        try:
            if name == "scan":
                self.scan(job, cmd)
            elif name == "inspect":
                self.inspect(job, cmd)
            else:
                self.run(job, cmd)
        except Exception as exc:  # noqa: BLE001
            emit(
                {
                    "type": "error",
                    "job": job,
                    "message": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=6),
                }
            )
            # A failed job must not poison the session — drop the browser and
            # bring a clean one back up for the next attempt.
            try:
                from uts_engine.automation.selenium_session import quit_driver

                quit_driver()
            except Exception:  # noqa: BLE001
                pass
            self.warm()
        finally:
            self.current_job = None
            emit({"type": "status", "state": "ready", "job": job})

    # --- command loop --------------------------------------------------

    def handle(self, cmd: dict) -> bool:
        """Returns False when the host should exit."""
        name = (cmd.get("cmd") or "").strip().lower()
        job = str(cmd.get("job") or "")

        if name == "shutdown":
            return False
        if name == "ping":
            emit({"type": "pong", "job": job})
            return True
        if name == "warm":
            self.warm()
            return True
        if name == "continue":
            # The customer says they have finished signing in.
            self.continue_event.set()
            emit({"type": "log", "line": "  Login confirmed by user — resuming"})
            return True
        if name not in ("scan", "run", "inspect"):
            emit({"type": "error", "job": job, "message": f"Unknown command: {name}"})
            return True

        if self.job_thread and self.job_thread.is_alive():
            emit({"type": "error", "job": job, "message": "A test is already running"})
            return True

        self.current_job = job
        self.job_thread = threading.Thread(
            target=self._run_job, args=(name, job, cmd), daemon=True
        )
        self.job_thread.start()
        return True


def main() -> int:
    host = EngineHost()
    try:
        host.boot()
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": f"Engine failed to boot: {exc}"})
        return 1

    # From here on the engine's own prints become log events.
    sys.stdout = _LogStream()  # type: ignore[assignment]

    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                cmd = json.loads(raw)
            except json.JSONDecodeError:
                emit({"type": "error", "message": f"Bad command JSON: {raw[:120]}"})
                continue
            if not host.handle(cmd):
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            from uts_engine.automation.selenium_session import shutdown_all

            shutdown_all()
        except Exception:  # noqa: BLE001
            pass
        emit({"type": "status", "state": "stopped"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
