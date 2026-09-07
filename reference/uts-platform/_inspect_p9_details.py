"""Get detailed failure messages for project 9 / execution 11."""
import json
import re
from pathlib import Path
from webapp import create_app
from webapp.models import TestCase, db

ROOT = Path(r"C:\Software_Automation\UTS-Test-Automation-Suite 3\UTS-Test-Automation-Suite")
app = create_app()
with app.app_context():
    for tc_id in (47, 48):
        tc = db.session.get(TestCase, tc_id)
        print("=" * 60)
        print(tc.external_key, tc.name)
        print("steps:")
        for i, st in enumerate(tc.automation_steps or [], 1):
            print(f"  {i}. {st}")

report = ROOT / "reports" / "e2e-report-20260810_162111.html"
text = report.read_text(encoding="utf-8", errors="replace")
# Extract FAIL messages roughly
print("\n===== REPORT FAIL DETAILS =====")
# strip tags lightly
plain = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
plain = re.sub(r"</tr>", "\n", plain, flags=re.I)
plain = re.sub(r"<[^>]+>", " | ", plain)
plain = re.sub(r"\s+\|\s+", " | ", plain)
for line in plain.splitlines():
    if any(k in line for k in ("FAIL", "FAIL]", "Timeout", "Unable", "no such", "Message", "TC_AI", "Step")):
        clean = re.sub(r"\s+", " ", line).strip(" |")
        if len(clean) > 20:
            print(clean[:300])

# also json results if any near that timestamp
print("\n===== JSON RESULTS =====")
for p in sorted((ROOT / "reports").glob("e2e-results-20260810_1621*.json")):
    data = json.loads(p.read_text(encoding="utf-8"))
    for item in data.get("automation") or []:
        print("-" * 40)
        print(item.get("id"), item.get("title"), item.get("status"))
        print("message:", item.get("message") or item.get("error") or "")
        for st in item.get("steps") or []:
            print(" ", st.get("status"), st.get("action"), st.get("object_name"), "=>", (st.get("message") or "")[:180])
