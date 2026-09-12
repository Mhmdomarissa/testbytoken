"""W6.5 regression: session present => no logout between scenarios.

The team lead's #1 complaint was a forced mid-run logout on an interactive
session with no credentials to sign back in with. host.py's EngineHost.run()
already guarded this correctly (logout_after_each=not has_session()); cli.py's
create_and_run() and worker/agent.py's _run_job() did not — same disease as
E1/E4, a fix applied at one call site instead of to the behavior. All three
now route through selenium_session.safe_logout_after_each().

Every test here asserts on the ACTUAL VALUE that reaches run_all_automation
(or create_and_run, for host.py)'s logout_after_each parameter — not just
that safe_logout_after_each() appears somewhere in the caller's source. A
call whose return value is computed and then discarded, or shadowed by a
stray `logout_after_each = True` two lines later, would pass a source-text
check and still reproduce the original bug; it cannot pass these.

No browser, no network required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


def test_safe_logout_after_each_gates_on_session(monkeypatch):
    import uts_engine.automation.selenium_session as selenium_session

    monkeypatch.setattr(selenium_session, "has_session", lambda: True)
    assert selenium_session.safe_logout_after_each(True) is False
    assert selenium_session.safe_logout_after_each(False) is False

    monkeypatch.setattr(selenium_session, "has_session", lambda: False)
    assert selenium_session.safe_logout_after_each(True) is True
    assert selenium_session.safe_logout_after_each(False) is False


def test_host_run_does_not_logout_with_a_live_session(monkeypatch):
    """host.py: with an interactive session present (no credentials to sign
    back in with), the inp dict EngineHost.run() hands to create_and_run
    must carry logout_after_each_test=False — the real _build_input() call,
    not reimplemented."""
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


def test_create_and_run_threads_safe_logout_value_to_run_all_automation(monkeypatch):
    """cli.py: the real create_and_run() body, executed end to end (every
    dependency between its entry and run_all_automation() is faked, but
    create_and_run() itself is NOT mocked) — with a session present, the
    logout_after_each kwarg run_all_automation actually receives must be
    False, even though app-input.json's logout_after_each_test says True.
    This is the CLI's own direct entry path, the one with no session
    awareness at all before this fix."""
    import uts_engine.automation.selenium_session as selenium_session
    import uts_engine.cli as cli_module
    from uts_engine.discovery.discovery import DiscoveryResult

    # safe_logout_after_each() calls has_session() via selenium_session's OWN
    # module globals, not whatever name cli.py imported it under — patching
    # cli_module.has_session alone does not affect it.
    monkeypatch.setattr(selenium_session, "has_session", lambda: True)
    monkeypatch.setattr(cli_module, "has_session", lambda: True)
    monkeypatch.setattr(cli_module, "save_actions_catalog", lambda: None)
    monkeypatch.setattr(cli_module, "start_browser", lambda url: None)
    monkeypatch.setattr(cli_module, "get_driver", lambda: None)

    fake_discovery = DiscoveryResult(
        url="http://example.invalid",
        username="u",
        app_name="App",
        page_title="App",
        discovered_at="2026-01-01T00:00:00",
        login_url="http://example.invalid",
        post_login_url="http://example.invalid",
        scenarios=[],
    )
    monkeypatch.setattr(cli_module, "discover_application", lambda *a, **kw: fake_discovery)
    monkeypatch.setattr(cli_module, "save_discovery", lambda d: Path("/tmp/fake-flow.json"))
    monkeypatch.setattr(cli_module, "generate_selenium_from_discovery", lambda d, out_dir: [])
    monkeypatch.setattr(cli_module, "write_html_report", lambda **kw: Path("/tmp/fake-report.html"))

    captured: dict = {}

    def fake_run_all_automation(discovery, password, logger, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli_module, "run_all_automation", fake_run_all_automation)

    inp = {
        "url": "http://example.invalid",
        "username": "u",
        "password": "p",
        # Config explicitly asks for a logout; a live session must still win.
        "logout_after_each_test": True,
        "ai_mode": False,
    }
    cli_module.create_and_run(inp, ["Module"], run_tests=True, open_outputs=False)

    assert "logout_after_each" in captured, "run_all_automation was never called"
    assert captured["logout_after_each"] is False, (
        "create_and_run computed a gated logout_after_each but did not "
        "thread that actual value through to run_all_automation"
    )


def test_worker_agent_run_job_threads_safe_logout_value_to_run_all_automation(monkeypatch):
    """worker/agent.py: the real _run_job() body for a STORED_EXECUTION job,
    executed end to end — with a session present, run_all_automation's
    logout_after_each kwarg must be False. This was the hardcoded
    logout_after_each=True call site; nothing here reimplements the check,
    it drives the real function."""
    import uts_engine.automation.selenium_session as selenium_session
    import uts_engine.discovery.automation_runner as automation_runner
    import uts_engine.exporters.report_generator as report_generator
    import uts_engine.worker.agent as agent_module

    monkeypatch.setattr(selenium_session, "has_session", lambda: True)
    # start_browser, run_all_automation and write_html_report are all
    # imported locally inside _run_job's STORED_EXECUTION branch (from
    # <module> import ...), so none of them are module-level attributes on
    # agent_module — a local import re-fetches the current attribute off
    # its real source module at call time, so patch each one there instead.
    monkeypatch.setattr(selenium_session, "start_browser", lambda url: None)
    monkeypatch.setattr(agent_module, "_progress", lambda *a, **kw: False)
    monkeypatch.setattr(agent_module, "_should_stop", lambda *a, **kw: False)
    monkeypatch.setattr(report_generator, "write_html_report", lambda **kw: Path("/tmp/fake-report.html"))

    captured: dict = {}

    def fake_run_all_automation(discovery, password, logger, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(automation_runner, "run_all_automation", fake_run_all_automation)

    job = {
        "id": 1,
        "job_type": "STORED_EXECUTION",
        "payload": {
            "job_type": "STORED_EXECUTION",
            "project": {"name": "App", "application_url": "http://example.invalid"},
            "input": {},
            "stored_scenarios": [
                {
                    "id": "TC_1",
                    "type": "automation",
                    "title": "Stored case",
                    "module": "Manual",
                    "steps": [],
                }
            ],
        },
    }

    status, _message, exit_code = agent_module._run_job(job, "http://server.invalid", "tok")

    assert "logout_after_each" in captured, "run_all_automation was never called"
    assert captured["logout_after_each"] is False, (
        "_run_job computed a gated logout_after_each but did not thread "
        "that actual value through to run_all_automation"
    )
    assert status == "COMPLETED"
    assert exit_code == 0
