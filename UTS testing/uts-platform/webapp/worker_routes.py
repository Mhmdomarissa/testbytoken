"""APIs for UTS Worker Agents running on user machines."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash

from webapp.models import Execution, Project, ScanHistory, User, WorkerAgent, WorkerJob, db
from webapp.uts_service import _archive, _complete_execution, persist_discovery, persist_modules
from webapp.worker_service import (
    create_worker_token,
    hash_token,
    mark_stale_workers_offline,
    utcnow,
)


worker_bp = Blueprint("worker", __name__, url_prefix="/api/worker")


def worker_token_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        token = token or request.headers.get("X-Worker-Token", "").strip()
        if not token:
            return jsonify(error="Worker token required"), 401
        worker = WorkerAgent.query.filter_by(token_hash=hash_token(token)).first()
        if not worker or not worker.user or not worker.user.is_active or worker.user.is_deleted:
            return jsonify(error="Invalid worker token"), 401
        g.worker = worker
        g.worker_user = worker.user
        return view(*args, **kwargs)

    return wrapped


@worker_bp.post("/register")
def register_worker():
    """Authenticate a platform user and register this machine as their worker."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    machine_name = (data.get("machine_name") or "").strip() or "Unknown PC"
    platform = (data.get("platform") or "").strip() or "unknown"
    browser = (data.get("browser") or "chrome").strip() or "chrome"

    user = User.query.filter(db.func.lower(User.username) == username.lower()).first()
    if (
        not user
        or user.is_deleted
        or not user.is_active
        or not check_password_hash(user.password_hash, password)
    ):
        return jsonify(error="Invalid username or password"), 401

    token = create_worker_token()
    # One active token/machine row per user+machine_name (replace old token).
    worker = WorkerAgent.query.filter_by(user_id=user.id, machine_name=machine_name).first()
    if not worker:
        worker = WorkerAgent(user_id=user.id, machine_name=machine_name)
        db.session.add(worker)
    worker.token_hash = hash_token(token)
    worker.platform = platform
    worker.browser = browser
    worker.status = "ONLINE"
    worker.last_seen_at = utcnow()
    db.session.commit()

    return jsonify(
        ok=True,
        worker_id=worker.id,
        token=token,
        username=user.username,
        machine_name=worker.machine_name,
        message="Worker registered. Keep this agent running while you use UTS.",
    )


@worker_bp.post("/heartbeat")
@worker_token_required
def heartbeat():
    worker: WorkerAgent = g.worker
    worker.last_seen_at = utcnow()
    if worker.status != "BUSY":
        worker.status = "ONLINE"
    mark_stale_workers_offline()
    db.session.commit()
    return jsonify(ok=True, status=worker.status, server_time=utcnow().isoformat())


@worker_bp.get("/next-job")
@worker_token_required
def next_job():
    worker: WorkerAgent = g.worker
    worker.last_seen_at = utcnow()

    job = (
        WorkerJob.query.filter(
            WorkerJob.user_id == worker.user_id,
            WorkerJob.status == "QUEUED",
        )
        .order_by(WorkerJob.created_at.asc())
        .first()
    )
    if not job:
        if worker.status != "BUSY":
            worker.status = "ONLINE"
        db.session.commit()
        return jsonify(ok=True, job=None)

    job.status = "CLAIMED"
    job.worker_id = worker.id
    job.claimed_at = utcnow()
    job.message = f"Claimed by {worker.machine_name}"
    worker.status = "BUSY"
    if job.history_id:
        history = db.session.get(ScanHistory, job.history_id)
        if history:
            history.status = "RUNNING"
            history.started_at = history.started_at or utcnow()
            history.message = f"Running on {worker.machine_name}"
    if job.execution_id:
        execution = db.session.get(Execution, job.execution_id)
        if execution:
            execution.status = "RUNNING"
            execution.started_at = execution.started_at or utcnow()
            execution.current_step = f"Browser opening on {worker.machine_name}"
    project = db.session.get(Project, job.project_id)
    if project:
        project.status = "SCANNING" if job.job_type == "MODULES" else "EXECUTING"
    db.session.commit()

    return jsonify(
        ok=True,
        job={
            "id": job.id,
            "job_type": job.job_type,
            "payload": job.payload or {},
            "stop_requested": job.stop_requested,
        },
    )


@worker_bp.post("/jobs/<int:job_id>/progress")
@worker_token_required
def job_progress(job_id: int):
    worker: WorkerAgent = g.worker
    job = db.session.get(WorkerJob, job_id)
    if not job or job.user_id != worker.user_id:
        return jsonify(error="Job not found"), 404

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    status = (data.get("status") or "RUNNING").strip().upper()
    if status not in {"RUNNING", "CLAIMED"}:
        status = "RUNNING"
    job.status = status
    if message:
        job.message = message[:1000]
    worker.last_seen_at = utcnow()
    worker.status = "BUSY"

    if job.history_id:
        history = db.session.get(ScanHistory, job.history_id)
        if history:
            history.status = "RUNNING"
            history.message = job.message
    if job.execution_id:
        execution = db.session.get(Execution, job.execution_id)
        if execution:
            execution.status = "RUNNING"
            execution.current_step = job.message[:500]
    db.session.commit()
    return jsonify(ok=True, stop_requested=bool(job.stop_requested))


@worker_bp.get("/jobs/<int:job_id>/status")
@worker_token_required
def job_status(job_id: int):
    worker: WorkerAgent = g.worker
    job = db.session.get(WorkerJob, job_id)
    if not job or job.user_id != worker.user_id:
        return jsonify(error="Job not found"), 404
    return jsonify(
        ok=True,
        status=job.status,
        stop_requested=bool(job.stop_requested),
        message=job.message,
    )


@worker_bp.post("/jobs/<int:job_id>/complete")
@worker_token_required
def complete_job(job_id: int):
    worker: WorkerAgent = g.worker
    job = db.session.get(WorkerJob, job_id)
    if not job or job.user_id != worker.user_id:
        return jsonify(error="Job not found"), 404

    data = request.get_json(silent=True) or {}
    final_status = (data.get("status") or "COMPLETED").strip().upper()
    if final_status not in {"COMPLETED", "FAILED", "STOPPED"}:
        final_status = "FAILED"
    message = (data.get("message") or "").strip() or final_status
    exit_code = int(data.get("exit_code") or (0 if final_status == "COMPLETED" else 1))
    artifacts = data.get("artifacts") or {}

    project = db.session.get(Project, job.project_id)
    history = db.session.get(ScanHistory, job.history_id) if job.history_id else None
    execution = db.session.get(Execution, job.execution_id) if job.execution_id else None

    root = Path(current_app.config["UTS_ROOT"])
    generated = root / "generated"
    reports = root / "reports"
    generated.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    def _write_artifact(name: str, relative: str) -> None:
        raw = artifacts.get(name)
        if not raw:
            return
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(raw, (dict, list)):
            path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            text = str(raw)
            if name.endswith("_b64"):
                path.write_bytes(base64.b64decode(text))
            else:
                path.write_text(text, encoding="utf-8")

    _write_artifact("modules", "generated/modules.json")
    _write_artifact("discovered_flow", "generated/discovered-flow.json")
    _write_artifact("page_map", "generated/page-map.json")
    _write_artifact("report_html", "reports/latest-e2e-report.html")

    try:
        if project and final_status == "COMPLETED":
            modules_path = generated / "modules.json"
            if modules_path.is_file():
                modules = json.loads(modules_path.read_text(encoding="utf-8-sig"))
                if isinstance(modules, dict):
                    modules = modules.get("modules") or modules.get("items") or []
                if isinstance(modules, list):
                    persist_modules(project, modules)
            flow_path = generated / "discovered-flow.json"
            page_map_path = generated / "page-map.json"
            if flow_path.is_file():
                flow = json.loads(flow_path.read_text(encoding="utf-8-sig"))
                page_map = (
                    json.loads(page_map_path.read_text(encoding="utf-8-sig"))
                    if page_map_path.is_file()
                    else {}
                )
                persist_discovery(project, flow, page_map)

        archive = None
        if project and history:
            archive = _archive(project.id, history.id)
            history.artifact_path = str(archive)
            history.status = final_status if final_status != "COMPLETED" else "COMPLETED"
            history.message = message
            history.completed_at = utcnow()
            if (generated / "modules.json").is_file():
                try:
                    modules = json.loads((generated / "modules.json").read_text(encoding="utf-8-sig"))
                    if isinstance(modules, dict):
                        modules = modules.get("modules") or []
                    history.module_count = len(modules) if isinstance(modules, list) else history.module_count
                except Exception:  # noqa: BLE001
                    pass

        if execution and archive is not None:
            if final_status == "STOPPED":
                execution.status = "STOPPED"
                execution.message = message
                execution.current_step = "Stopped on worker machine"
                execution.completed_at = utcnow()
            else:
                _complete_execution(execution, exit_code, archive)
                execution.current_step = message[:500]

        if project:
            if final_status == "COMPLETED":
                project.status = "SCANNED" if job.job_type == "MODULES" else "READY"
            elif final_status == "STOPPED":
                project.status = "STOPPED"
            else:
                project.status = "FAILED"

        job.status = final_status
        job.message = message
        job.result = {"exit_code": exit_code, "artifact_keys": list(artifacts.keys())}
        job.completed_at = utcnow()
        worker.status = "ONLINE"
        worker.last_seen_at = utcnow()
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        job.status = "FAILED"
        job.message = str(exc)
        job.completed_at = utcnow()
        worker.status = "ONLINE"
        db.session.commit()
        return jsonify(ok=False, error=str(exc)), 500

    return jsonify(ok=True, status=job.status)
