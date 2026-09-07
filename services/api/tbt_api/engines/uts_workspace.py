"""uts_workspace.py — one UTS engine per user.

A workspace is a long-lived uts_engine.host process with its own working
directory. It is created the moment a customer starts typing, so Chrome is
already up by the time they hit enter, and it is reaped once they go idle.

Today a workspace is a process on this machine. The interface here — create,
warm, submit, events, reap — is deliberately the same shape a container-backed
implementation needs, so swapping the backing out later does not touch the API.

State lives in memory only. Anything worth keeping is pulled out of the job
result and stored by the control plane.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

# Repo root — five levels above this file (services/api/tbt_api/engines/).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
ENGINE_ROOT = REPO_ROOT / "services" / "engine"
ENGINE_HOST = ENGINE_ROOT / "uts_engine" / "host.py"

# The engine (Selenium) and the API (FastAPI + Playwright) keep permanently
# separate virtualenvs — services/engine/.venv vs services/api/.venv — so the
# two browser stacks never share a process. Never point ENGINE_PYTHON at the
# API's own venv, and never import engine code into this process directly.
ENGINE_PYTHON = ENGINE_ROOT / ".venv" / "Scripts" / "python.exe"
if not ENGINE_PYTHON.is_file():
    ENGINE_PYTHON = ENGINE_ROOT / ".venv" / "bin" / "python"

WORKSPACES_DIR = Path(os.environ.get("TAAS_WORKSPACES_DIR", REPO_ROOT / "workspaces"))
IDLE_TIMEOUT_SECONDS = int(os.environ.get("TAAS_WORKSPACE_IDLE_SECONDS", "1800"))
BOOT_TIMEOUT_SECONDS = 30


class Job:
    """One scan or run. Events accumulate so a client can reconnect and catch up."""

    def __init__(self, job_id: str, kind: str) -> None:
        self.id = job_id
        self.kind = kind
        self.events: list[dict] = []
        # queued | running | awaiting_login | done | error
        self.status = "queued"
        self.result: dict | None = None
        self.error: str | None = None
        self.awaiting: dict | None = None
        self.created_at = time.time()

    def snapshot(self, *, with_result: bool = True) -> dict:
        snap = {
            "job_id": self.id,
            "kind": self.kind,
            "status": self.status,
            "error": self.error,
            "awaiting_login": self.awaiting,
            "event_count": len(self.events),
            "created_at": self.created_at,
        }
        if with_result:
            snap["result"] = self.result
        return snap


class Workspace:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.workdir = WORKSPACES_DIR / session_id
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.proc: subprocess.Popen | None = None
        self.state = "new"
        self.jobs: dict[str, Job] = {}
        self.current_job: str | None = None
        self.last_used = time.time()
        # Reentrant: start/submit/reset and the stdout reader thread all take it.
        self.lock = threading.RLock()
        self.reader: threading.Thread | None = None
        self.boot_error: str | None = None

    # --- process lifecycle ---------------------------------------------

    def start(self) -> None:
        # Guarded: warm(), submit() and reset() all call this, and concurrent
        # requests racing the check would each spawn an engine. The extra one is
        # untracked, so its Chrome never gets reaped.
        with self.lock:
            self._start_locked()

    def _start_locked(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        env = dict(os.environ)
        env["UTS_WORKDIR"] = str(self.workdir)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            [str(ENGINE_PYTHON), str(ENGINE_HOST)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(ENGINE_ROOT),
        )
        self.state = "booting"
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in self.proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                event = {"type": "log", "line": raw}
            self._handle_event(event)
        self.state = "stopped"

    def _handle_event(self, event: dict) -> None:
        kind = event.get("type")
        with self.lock:
            if kind == "status":
                state = event.get("state") or ""
                # "warm"/"warming" describe the browser, not readiness to accept
                # work, so they must not clobber a busy state.
                if state in ("booting", "ready", "busy", "stopped", "warm_failed"):
                    self.state = state
                elif state in ("warming", "warm") and self.state != "busy":
                    self.state = state

            job_id = event.get("job") or self.current_job
            job = self.jobs.get(job_id) if job_id else None
            if job is None:
                return

            job.events.append(event)
            if kind == "result":
                job.status = "done" if event.get("ok") else "error"
                job.result = event.get("data") or {}
                if not event.get("ok") and not job.error:
                    job.error = (job.result or {}).get("message") or "Run reported failure"
                self.current_job = None
            elif kind == "error":
                job.status = "error"
                job.error = event.get("message") or "Engine error"
                self.current_job = None
            elif kind == "awaiting_login":
                # The customer is signing in themselves. Nothing is captured
                # while they type; we only learn the session afterwards.
                job.status = "awaiting_login"
                job.awaiting = {
                    "url": event.get("url"),
                    "message": event.get("message"),
                    "timeout_seconds": event.get("timeout_seconds"),
                }
            elif kind == "login_captured":
                job.status = "running"
                job.awaiting = None
            elif kind in ("log", "step"):
                if job.status == "queued":
                    job.status = "running"

    def _kill_tree(self) -> None:
        """Hard-kill the engine and everything under it.

        On Windows a venv's python.exe re-execs the base interpreter as a child,
        so the engine we launched is the launcher and the real process is its
        child — and chromedriver hangs off that. proc.kill() reaps only the
        launcher, orphaning the engine and leaving a stray Chrome behind. The
        graceful shutdown above is the normal path; this is the fallback.
        """
        if not self.proc:
            return
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                return
            except Exception:  # noqa: BLE001
                pass
        try:
            self.proc.kill()
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.poll() is None and self.proc.stdin:
                self.proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=20)
        except Exception:  # noqa: BLE001
            pass
        finally:
            if self.proc.poll() is None:
                self._kill_tree()
            self.state = "stopped"

    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    # --- commands -------------------------------------------------------

    def _send(self, command: dict) -> None:
        if not self.alive():
            raise RuntimeError("Workspace engine is not running")
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()
        self.last_used = time.time()

    def warm(self) -> None:
        self.start()
        if self.alive():
            self._send({"cmd": "warm"})

    def resume(self, job_id: str) -> None:
        """Tell the engine the customer has finished signing in."""
        self._send({"cmd": "continue", "job": job_id})

    def reset(self) -> None:
        """Kill the engine and bring a clean one up, abandoning any running job.

        The escape hatch for when a run wedges: without it a stuck job leaves
        current_job set forever and every later attempt is refused.
        """
        with self.lock:
            stranded = self.current_job
            self.current_job = None
        if stranded and (job := self.jobs.get(stranded)) and job.status not in ("done", "error"):
            job.status = "error"
            job.error = "Cancelled — engine was reset"
        self.stop()
        self.start()

    def submit(self, kind: str, payload: dict) -> Job:
        # A job only clears itself via a result/error event. If the engine died
        # mid-run those never arrive, so verify the claim is still real rather
        # than refusing work forever.
        if self.current_job and not self.alive():
            with self.lock:
                self.current_job = None
        self.start()
        with self.lock:
            if self.current_job:
                raise RuntimeError(
                    "This workspace is already running a test. Use Reset engine to stop it."
                )
            job = Job(uuid.uuid4().hex[:12], kind)
            self.jobs[job.id] = job
            self.current_job = job.id
        command = dict(payload)
        command["cmd"] = kind
        command["job"] = job.id
        try:
            self._send(command)
        except Exception:
            with self.lock:
                self.current_job = None
                job.status = "error"
                job.error = "Could not reach the engine process"
            raise
        return job

    def stderr_tail(self, lines: int = 12) -> str:
        """Best-effort engine stderr, for surfacing a boot failure."""
        if not self.proc or not self.proc.stderr:
            return ""
        try:
            if self.proc.poll() is None:
                return ""
            return "\n".join(self.proc.stderr.read().strip().splitlines()[-lines:])
        except Exception:  # noqa: BLE001
            return ""

    def job_list(self) -> list[dict]:
        """Jobs this workspace has run, newest first.

        Lets a client that lost its event stream — a reload, a network blip —
        find the work it started instead of stranding on a spinner while the
        result sits here in memory.
        """
        jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j.snapshot(with_result=False) for j in jobs]

    def info(self) -> dict:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "alive": self.alive(),
            "workdir": str(self.workdir),
            "current_job": self.current_job,
            "idle_seconds": round(time.time() - self.last_used),
        }


class WorkspaceManager:
    def __init__(self) -> None:
        self._spaces: dict[str, Workspace] = {}
        self._lock = threading.Lock()
        self._reaper = threading.Thread(target=self._reap_loop, daemon=True)
        self._reaper.start()

    def get_or_create(self, session_id: str | None) -> Workspace:
        session_id = (session_id or "").strip() or uuid.uuid4().hex[:16]
        with self._lock:
            space = self._spaces.get(session_id)
            died = space is not None and space.state == "stopped" and not space.alive()
            if space is None or died:
                space = Workspace(session_id)
                self._spaces[session_id] = space
        return space

    def get(self, session_id: str) -> Workspace | None:
        return self._spaces.get(session_id)

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._spaces.pop(session_id, None)

    def find_job(self, job_id: str) -> tuple[Workspace, Job] | tuple[None, None]:
        for space in list(self._spaces.values()):
            job = space.jobs.get(job_id)
            if job:
                return space, job
        return None, None

    def _reap_loop(self) -> None:
        while True:
            time.sleep(60)
            now = time.time()
            for sid, space in list(self._spaces.items()):
                idle = now - space.last_used
                if space.current_job:
                    continue
                if idle > IDLE_TIMEOUT_SECONDS or not space.alive():
                    try:
                        space.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    if not space.alive():
                        self._spaces.pop(sid, None)

    def shutdown_all(self) -> None:
        for space in list(self._spaces.values()):
            try:
                space.stop()
            except Exception:  # noqa: BLE001
                pass
        self._spaces.clear()

    def stats(self) -> dict:
        return {
            "workspaces": [s.info() for s in self._spaces.values()],
            "engine_python": str(ENGINE_PYTHON),
            "engine_available": ENGINE_HOST.is_file() and ENGINE_PYTHON.is_file(),
        }


manager = WorkspaceManager()
