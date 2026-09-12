"""W6.5 regression: session present => no logout between scenarios.

The team lead's #1 complaint was a forced mid-run logout on an interactive
session with no credentials to sign back in with. host.py's EngineHost.run()
already guarded this correctly (logout_after_each=not has_session()); cli.py's
create_and_run() and worker/agent.py's _run_job() did not — same disease as
E1/E4, a fix applied at one call site instead of to the behavior. All three
now route through selenium_session.safe_logout_after_each(); this file locks
that in, both for the shared helper and for each of the three entry paths.

No browser required.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch


def test_safe_logout_after_each_gates_on_session(monkeypatch):
    import uts_engine.automation.selenium_session as selenium_session

    monkeypatch.setattr(selenium_session, "has_session", lambda: True)
    assert selenium_session.safe_logout_after_each(True) is False
    assert selenium_session.safe_logout_after_each(False) is False

    monkeypatch.setattr(selenium_session, "has_session", lambda: False)
    assert selenium_session.safe_logout_after_each(True) is True
    assert selenium_session.safe_logout_after_each(False) is False


def _uses_safe_logout_gate(func) -> bool:
    return "safe_logout_after_each(" in inspect.getsource(func)


def test_cli_create_and_run_uses_safe_logout_gate():
    from uts_engine.cli import create_and_run

    assert _uses_safe_logout_gate(create_and_run), (
        "create_and_run must derive logout_after_each via "
        "safe_logout_after_each(), not a raw config value — this is the "
        "exact bug reported on the CLI entry path."
    )


def test_worker_agent_run_job_uses_safe_logout_gate():
    from uts_engine.worker.agent import _run_job

    assert _uses_safe_logout_gate(_run_job), (
        "_run_job's direct run_all_automation() call must gate "
        "logout_after_each through safe_logout_after_each(), not a "
        "hardcoded True — this is the exact bug reported on the worker "
        "entry path."
    )


def test_host_engine_host_run_uses_safe_logout_gate():
    from uts_engine.host import EngineHost

    assert _uses_safe_logout_gate(EngineHost.run), (
        "EngineHost.run should route through the same shared helper as "
        "the other two entry paths rather than re-deriving the same "
        "safety check inline."
    )


def test_host_run_does_not_logout_with_a_live_session(monkeypatch):
    """Behavioral check on the one entry path that already claimed to be
    gated: with an interactive session present (no credentials to sign
    back in with), the inp dict handed to create_and_run must carry
    logout_after_each_test=False."""
    import uts_engine.automation.selenium_session as selenium_session
    import uts_engine.host as host_module

    monkeypatch.setattr(selenium_session, "has_session", lambda: True)

    captured: dict = {}

    def fake_create_and_run(inp, modules, **kwargs):
        captured["inp"] = inp
        return 0

    engine = host_module.EngineHost()
    engine.warm = lambda: None  # no real browser pre-launch in a test

    with patch("uts_engine.cli.create_and_run", side_effect=fake_create_and_run):
        engine.run(
            "job1",
            {"url": "http://example.invalid", "modules": ["X"], "interactive": True},
        )

    assert captured, "create_and_run was never called"
    assert captured["inp"]["logout_after_each_test"] is False
