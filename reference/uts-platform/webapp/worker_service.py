"""Dispatch automation jobs to the logged-in user's online worker machine."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from webapp.models import Project, WorkerAgent, WorkerJob, db
from webapp.uts_service import _project_input


ONLINE_WINDOW_SECONDS = 90


def utcnow() -> datetime:
    return datetime.utcnow()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_worker_token() -> str:
    return secrets.token_urlsafe(32)


def find_online_worker(user_id: int) -> WorkerAgent | None:
    cutoff = utcnow() - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    return (
        WorkerAgent.query.filter(
            WorkerAgent.user_id == user_id,
            WorkerAgent.status.in_(("ONLINE", "BUSY")),
            WorkerAgent.last_seen_at.isnot(None),
            WorkerAgent.last_seen_at >= cutoff,
        )
        .order_by(WorkerAgent.last_seen_at.desc())
        .first()
    )


def mark_stale_workers_offline() -> None:
    cutoff = utcnow() - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    stale = WorkerAgent.query.filter(
        WorkerAgent.status.in_(("ONLINE", "BUSY")),
        WorkerAgent.last_seen_at < cutoff,
    ).all()
    for worker in stale:
        worker.status = "OFFLINE"
    if stale:
        db.session.commit()


def enqueue_job(
    *,
    user_id: int,
    project: Project,
    job_type: str,
    history_id: int | None = None,
    execution_id: int | None = None,
    selected_modules: list[str] | None = None,
    test_case_ids: list[int] | None = None,
    execute: bool = False,
    stored_scenarios: list[dict] | None = None,
) -> WorkerJob | None:
    """Queue a job for the user's online worker. Returns None if no worker is online."""
    worker = find_online_worker(user_id)
    if not worker:
        return None

    payload = {
        "project": {
            "id": project.id,
            "name": project.name,
            "application_url": project.application_url,
            "app_username": project.app_username or "",
            "app_password": project.app_password or "",
            "app_role": project.app_role or "",
            "browser": project.browser or worker.browser or "chrome",
        },
        "input": _project_input(project),
        "selected_modules": selected_modules or [],
        "test_case_ids": test_case_ids or [],
        "stored_scenarios": stored_scenarios or [],
        "execute": execute,
        "job_type": job_type,
        "history_id": history_id,
        "execution_id": execution_id,
    }
    payload["input"]["browser"] = payload["project"]["browser"]
    if selected_modules:
        payload["input"]["module"] = "#".join(selected_modules)
    payload["input"]["run_automation"] = execute

    job = WorkerJob(
        user_id=user_id,
        worker_id=worker.id,
        project_id=project.id,
        history_id=history_id,
        execution_id=execution_id,
        job_type=job_type,
        payload=payload,
        status="QUEUED",
        message=f"Queued for {worker.machine_name or 'worker machine'}",
    )
    db.session.add(job)
    db.session.commit()
    return job


def request_stop_for_user(user_id: int, project_id: int | None = None) -> int:
    query = WorkerJob.query.filter(
        WorkerJob.user_id == user_id,
        WorkerJob.status.in_(("QUEUED", "CLAIMED", "RUNNING")),
    )
    if project_id:
        query = query.filter_by(project_id=project_id)
    count = 0
    for job in query.all():
        job.stop_requested = True
        job.message = "Stop requested"
        count += 1
    if count:
        db.session.commit()
    return count
