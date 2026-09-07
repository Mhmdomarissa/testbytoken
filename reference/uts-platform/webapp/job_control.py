"""Cooperative cancel flag for web scan / automation jobs."""

from __future__ import annotations

import threading

_stop = threading.Event()
_lock = threading.Lock()
_active_project_id: int | None = None
_active_execution_id: int | None = None
_active_history_id: int | None = None


class JobStopped(Exception):
    """Raised when the user requests stop from the web UI."""


def clear_stop() -> None:
    _stop.clear()


def request_stop() -> None:
    _stop.set()


def is_stop_requested() -> bool:
    return _stop.is_set()


def set_active_job(
    project_id: int | None = None,
    execution_id: int | None = None,
    history_id: int | None = None,
) -> None:
    global _active_project_id, _active_execution_id, _active_history_id
    with _lock:
        _active_project_id = project_id
        _active_execution_id = execution_id
        _active_history_id = history_id


def get_active_job() -> dict:
    with _lock:
        return {
            "project_id": _active_project_id,
            "execution_id": _active_execution_id,
            "history_id": _active_history_id,
            "stop_requested": _stop.is_set(),
        }


def raise_if_stopped(message: str = "Stopped by user") -> None:
    if _stop.is_set():
        raise JobStopped(message)
