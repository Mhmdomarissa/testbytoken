"""Inspect project 9 failures on remote UTS server."""
from pathlib import Path
from webapp import create_app
from webapp.models import Execution, ExecutionStep, Module, Project, ScanHistory, TestCase, db

app = create_app()
with app.app_context():
    p = db.session.get(Project, 9)
    print("PROJECT", p.id if p else None, p.name if p else None)
    if not p:
        raise SystemExit(1)
    print("status", p.status)
    print("url", p.application_url)
    print("browser", p.browser)
    print("user", p.app_username)
    print("role", p.app_role)
    print("has_password", bool(p.app_password))

    print("\n--- MODULES ---")
    for m in Module.query.filter_by(project_id=9).order_by(Module.name).all():
        print(f"  id={m.id} selected={m.selected} name={m.name}")

    print("\n--- RECENT SCANS ---")
    for h in ScanHistory.query.filter_by(project_id=9).order_by(ScanHistory.id.desc()).limit(8).all():
        print(f"  #{h.id} {h.scan_type} {h.status} | {h.message}")

    print("\n--- RECENT EXECUTIONS ---")
    for e in Execution.query.filter_by(project_id=9).order_by(Execution.id.desc()).limit(8).all():
        print(f"  #{e.id} {e.status} pass={e.passed} fail={e.failed} total={e.total}")
        print(f"     msg={e.message}")
        print(f"     step={e.current_step}")
        print(f"     modules={e.module_names}")
        print(f"     tc_ids={e.test_case_ids}")
        print(f"     report={e.report_path}")

    e = Execution.query.filter_by(project_id=9).order_by(Execution.id.desc()).first()
    if e:
        print(f"\n--- STEPS for execution #{e.id} ---")
        steps = ExecutionStep.query.filter_by(execution_id=e.id).order_by(ExecutionStep.sequence).all()
        if not steps:
            print("  (no ExecutionStep rows)")
        for s in steps[:40]:
            print(f"  [{s.status}] {s.test_case_key} | {s.name} | {s.message}")

    print("\n--- TEST CASES ---")
    for tc in TestCase.query.filter_by(project_id=9).order_by(TestCase.id).all():
        steps = tc.automation_steps or tc.manual_steps or []
        print(f"  #{tc.id} {tc.external_key} type={tc.test_type} steps={len(steps)} name={tc.name}")

    # Peek latest report summary if present
    report = Path(e.report_path) if e and e.report_path else None
    if report and report.is_file():
        text = report.read_text(encoding="utf-8", errors="replace")
        print("\n--- REPORT SNIPPET ---")
        for line in text.splitlines():
            low = line.lower()
            if any(k in low for k in ("fail", "pass", "error", "tc_", "title", "reason", "message")):
                print(line.strip()[:220])
