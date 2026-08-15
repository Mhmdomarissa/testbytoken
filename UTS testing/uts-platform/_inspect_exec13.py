"""Inspect execution 13 and report details on remote server."""
import json
import re
from pathlib import Path
from webapp import create_app
from webapp.models import Execution, TestCase, db

ROOT = Path(r"C:\Software_Automation\UTS-Test-Automation-Suite 3\UTS-Test-Automation-Suite")
app = create_app()
with app.app_context():
    e = db.session.get(Execution, 13)
    print("EXEC", e.id if e else None)
    if not e:
        raise SystemExit(1)
    print("status", e.status)
    print("passed", e.passed, "failed", e.failed, "total", e.total)
    print("message", e.message)
    print("step", e.current_step)
    print("modules", e.module_names)
    print("tc_ids", e.test_case_ids)
    print("report_path", e.report_path)
    p = Path(e.report_path) if e.report_path else None
    print("report_exists", bool(p and p.is_file()))

    if e.test_case_ids:
        for tid in e.test_case_ids:
            tc = db.session.get(TestCase, tid)
            if not tc:
                continue
            print("=" * 50)
            print(tc.id, tc.external_key, tc.name)
            for i, st in enumerate(tc.automation_steps or [], 1):
                print(f"  {i}. {st.get('action')} | {st.get('object_name')} | {st.get('input_value')} | {st.get('locator_value','')[:80]}")

# Find matching json results
print("\n===== JSON RESULTS =====")
cands = sorted((ROOT / "reports").glob("e2e-results-*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:8]
for jp in cands:
    data = json.loads(jp.read_text(encoding="utf-8"))
    auto = data.get("automation") or []
    titles = [a.get("title") or a.get("id") for a in auto]
    print(jp.name, "->", titles, "summary", data.get("summary"))
    # print detail for latest few
    if "162" in jp.name or "17" in jp.name or True:
        for item in auto:
            print("-", item.get("id"), item.get("title"), item.get("status"), "|", (item.get("message") or "")[:120])
            for st in item.get("steps") or []:
                print("   ", st.get("status"), st.get("action"), st.get("object_name"), "=>", (st.get("message") or "")[:160])
        print()
