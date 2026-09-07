"""base.py — the abstract interface both engines satisfy.

Two engines exist behind this: PlaywrightEngine (playwright_runner.py — seven
fixed read-only checks, ~4 seconds, no container) and UtsEngine
(uts_workspace.py — a per-user engine process, deep crawl, generated suite,
authenticated journeys, minutes not seconds). They are deliberately kept
separate rather than merged; this module exists so route handlers and any
future code can depend on "a thing that runs tests" without importing either
engine module directly.

Both adapters below wrap their engine's real API as-is — start_run() adapts
around it rather than changing it. In particular PlaywrightEngine must not
touch playwright_runner.py's own logic (it is proven working; see
CLAUDE.md and the module's own docstring).

Which engine serves which endpoint — and, per docs/UTS_INTEGRATION_PLAN.md
Part 3, which one eventually serves the anonymous front page — is a routing
decision this module deliberately does not make. The UTS hosting model (API
link vs. hosted container) is still an open decision; nothing here encodes
either choice.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EngineRun(ABC):
    """Handle to one run, in progress or finished."""

    @property
    @abstractmethod
    def id(self) -> str:
        ...

    @abstractmethod
    def status(self) -> str:
        """queued | running | awaiting_login | done | error"""

    @abstractmethod
    def events(self, since: int = 0) -> list[dict]:
        """Progress events from `since` onward, oldest first."""

    @abstractmethod
    def result(self) -> dict | None:
        """The finished result dict, or None while still running."""


class TestEngine(ABC):
    """Common shape for anything that can run a test against a target: start a
    run and get back a handle that reports progress and, eventually, a result.
    """

    @abstractmethod
    def start_run(self, target: str, **options: Any) -> EngineRun:
        ...


class PlaywrightRun(EngineRun):
    """A PlaywrightEngine run is synchronous — by the time this handle exists,
    the run has already finished, so status()/result() have nothing to wait on.
    """

    def __init__(self, run_id: str, result: dict) -> None:
        self._id = run_id
        self._result = result

    @property
    def id(self) -> str:
        return self._id

    def status(self) -> str:
        return "done"

    def events(self, since: int = 0) -> list[dict]:
        return []

    def result(self) -> dict | None:
        return self._result


class PlaywrightEngine(TestEngine):
    """Adapts runner.py's synchronous run_test() to the common interface.

    Does not change run_test()'s own logic (see playwright_runner.py's
    docstring — it is proven working, wrap it, don't rewrite it) — it just runs
    it to completion inside start_run() and hands back an already-finished
    handle.
    """

    def __init__(self, shots_dir: str = "./shots") -> None:
        self._shots_dir = shots_dir

    def start_run(
        self, target: str, *, checks: list[str] | None = None, shots_dir: str | None = None, **_ignored: Any
    ) -> EngineRun:
        from tbt_api.engines.playwright_runner import run_test

        result = run_test(target, checks=checks, shots_dir=shots_dir or self._shots_dir)
        return PlaywrightRun(result.get("run_id", ""), result)


class UtsRun(EngineRun):
    """Thin view over a uts_workspace.Job — asynchronous and session-scoped."""

    def __init__(self, job) -> None:
        self._job = job

    @property
    def id(self) -> str:
        return self._job.id

    def status(self) -> str:
        return self._job.status

    def events(self, since: int = 0) -> list[dict]:
        return [dict(e) for e in self._job.events[since:]]

    def result(self) -> dict | None:
        return self._job.result if self._job.status == "done" else None


class UtsEngine(TestEngine):
    """Adapts the per-session Workspace/WorkspaceManager to the common
    interface without changing their own logic — session lifecycle, the
    interactive login handoff and SSE streaming stay in uts_workspace.py;
    this only wraps submit() so callers of the interface don't need to know
    that engine's job model.
    """

    def __init__(self) -> None:
        from tbt_api.engines.uts_workspace import manager

        self._manager = manager

    def start_run(
        self, target: str, *, session_id: str | None = None, kind: str = "scan", **payload: Any
    ) -> EngineRun:
        space = self._manager.get_or_create(session_id)
        job = space.submit(kind, {"url": target, **payload})
        return UtsRun(job)

    def shutdown_all(self) -> None:
        self._manager.shutdown_all()
