from pathlib import Path
from webapp import create_app
from webapp.models import Execution, db

REMOTE = Path(r"C:\Software_Automation\UTS-Test-Automation-Suite 3\UTS-Test-Automation-Suite")
app = create_app()
with app.app_context():
    e = db.session.get(Execution, 11)
    print("status", e.status if e else None)
    print("report_path", e.report_path if e else None)
    p = Path(e.report_path) if e and e.report_path else None
    print("exists", bool(p and p.is_file()))
    print("webdata", (REMOTE / "web-data").resolve())
    if p:
        try:
            print("resolved", p.resolve())
            print("under_webdata", str((REMOTE / "web-data").resolve()) in str(p.resolve()))
        except Exception as exc:
            print("resolve_err", exc)
    print("--- reports html ---")
    for x in sorted((REMOTE / "reports").glob("*.html"))[-8:]:
        print(x, x.stat().st_size)
    print("--- web-data html ---")
    for x in sorted((REMOTE / "web-data").rglob("*e2e*.html"))[-10:]:
        print(x, x.stat().st_size)
