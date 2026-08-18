"""uts_routes.py — the signed-in journey, powered by the UTS engine.

This is the second customer touchpoint: they have seen the homepage, signed up,
and want to test their first real application. The flow is deliberately a
click-through rather than one dense page:

    POST /uts/workspace       fired on the first keystroke — boots their engine
    POST /uts/scan            crawl the app, discover its modules
    GET  /uts/jobs/{id}/events   live progress (SSE)
    POST /uts/run             generate + execute tests for the chosen modules
    GET  /uts/jobs/{id}       snapshot, for reconnects and polling clients

Identity is a stubbed opaque session id for now. There is no auth in this
service yet; when accounts land, session_id becomes the user id and nothing
else here changes.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from workspaces import manager

router = APIRouter(prefix="/uts", tags=["uts"])


class WorkspaceRequest(BaseModel):
    session_id: str | None = None


class ScanRequest(BaseModel):
    session_id: str
    url: str
    app_name: str = ""
    role: str = ""
    # Interactive login is the default and the point of the product: the customer
    # signs in themselves — password, OTP, 2FA, CAPTCHA, SSO — and we keep only
    # the resulting session. See docs/CREDENTIALS.md.
    interactive: bool = True
    # Form-login fallback for apps with throwaway test accounts. Never store or
    # log these; they are passed straight through to the engine for one run.
    username: str = ""
    password: str = ""


class RunRequest(ScanRequest):
    modules: list[str]


class InspectRequest(ScanRequest):
    module: str = ""


@router.post("/workspace")
def create_workspace(req: WorkspaceRequest):
    """Boot (or reuse) this user's engine and start warming Chrome.

    Called as soon as the customer starts typing, so the browser is already up
    when they hit enter. Safe to call repeatedly.
    """
    space = manager.get_or_create(req.session_id or uuid.uuid4().hex[:16])
    try:
        space.warm()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Could not start the test engine: {exc}") from exc
    return {"session_id": space.session_id, **space.info()}


@router.get("/workspace/{session_id}")
def workspace_status(session_id: str):
    space = manager.get(session_id)
    if not space:
        raise HTTPException(404, "No workspace for that session")
    return space.info()


@router.post("/workspace/{session_id}/reset")
def reset_workspace(session_id: str):
    """Kill whatever is running and bring a clean engine up under the same session."""
    space = manager.get_or_create(session_id)
    try:
        space.reset()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Could not reset the engine: {exc}") from exc
    return {"session_id": space.session_id, "reset": True, **space.info()}


@router.delete("/workspace/{session_id}")
def stop_workspace(session_id: str):
    """Tear a user's engine down now rather than waiting for the idle reaper."""
    space = manager.get(session_id)
    if not space:
        raise HTTPException(404, "No workspace for that session")
    space.stop()
    manager.forget(session_id)
    return {"session_id": session_id, "stopped": True}


def _submit(kind: str, req: ScanRequest, extra: dict | None = None):
    space = manager.get_or_create(req.session_id)
    payload = {
        "url": req.url,
        "username": req.username,
        "password": req.password,
        "app_name": req.app_name,
        "role": req.role,
        "interactive": req.interactive,
    }
    payload.update(extra or {})
    try:
        job = space.submit(kind, payload)
    except RuntimeError as exc:
        detail = str(exc)
        tail = space.stderr_tail()
        if tail:
            detail = f"{detail} — engine said: {tail}"
        raise HTTPException(409, detail) from exc
    return {"job_id": job.id, "session_id": space.session_id, "kind": kind}


@router.post("/scan")
def scan(req: ScanRequest):
    """Crawl the target application and report the modules it found."""
    if not req.url.strip():
        raise HTTPException(400, "A target URL is required.")
    return _submit("scan", req)


@router.post("/run")
def run(req: RunRequest):
    """Generate and execute tests for the modules the customer picked."""
    modules = [m.strip() for m in req.modules if m and m.strip()]
    if not modules:
        raise HTTPException(400, "Pick at least one module to test.")
    return _submit("run", req, {"modules": modules})


@router.post("/jobs/{job_id}/continue")
def continue_job(job_id: str):
    """The customer has finished signing in — resume the parked job.

    Nothing about the login is sent here: no credentials, no page contents. This
    is only the "I'm done" signal.
    """
    space, job = manager.find_job(job_id)
    if not job or not space:
        raise HTTPException(404, "Unknown job")
    if job.status != "awaiting_login":
        raise HTTPException(409, f"Job is not waiting for a login (status: {job.status})")
    try:
        space.resume(job_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Could not reach the engine: {exc}") from exc
    return {"job_id": job_id, "resumed": True}


@router.post("/inspect")
def inspect(req: InspectRequest):
    """Open one module and list everything on it: tabs, links, buttons, fields.

    A scan says the module exists. This says what a user can do inside it.
    """
    if not req.url.strip():
        raise HTTPException(400, "A target URL is required.")
    return _submit("inspect", req, {"module": req.module})


@router.get("/jobs/{job_id}")
def job_snapshot(job_id: str):
    _space, job = manager.find_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job.snapshot()


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, since: int = 0):
    """Server-sent events for one job.

    Events are buffered per job and served by index, so a dropped connection can
    reconnect with ?since=N and lose nothing.
    """
    _space, job = manager.find_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")

    async def stream():
        cursor = max(0, since)
        idle = 0.0
        while True:
            events = job.events[cursor:]
            if events:
                idle = 0.0
                for offset, event in enumerate(events):
                    payload = dict(event)
                    payload["index"] = cursor + offset
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
                cursor += len(events)
            if job.status in ("done", "error") and cursor >= len(job.events):
                final = {"type": "end", "status": job.status, "error": job.error}
                yield f"data: {json.dumps(final)}\n\n"
                return
            await asyncio.sleep(0.2)
            idle += 0.2
            if idle >= 15:
                idle = 0.0
                yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}/report", response_class=HTMLResponse)
def job_report(job_id: str):
    """The engine's own HTML report for a finished run."""
    _space, job = manager.find_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    path = (job.result or {}).get("report_html") or ""
    if not path or not Path(path).is_file():
        raise HTTPException(404, "No report for this job yet")
    return HTMLResponse(Path(path).read_text(encoding="utf-8", errors="replace"))


@router.get("/debug/workspaces")
def debug_workspaces():
    return manager.stats()
