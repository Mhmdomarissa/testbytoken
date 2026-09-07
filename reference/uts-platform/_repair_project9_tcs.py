"""Repair project 9 AI test cases that incorrectly require login on PMI.org."""
from webapp import create_app
from webapp.models import Project, TestCase, db

URL = "https://www.pmi.org/"

OPEN_STEPS = [
    {
        "step_no": 1,
        "action": "Navigate",
        "object_name": "Application URL",
        "input_value": URL,
        "locator_by": "",
        "locator_value": "",
        "expected": "Application page",
    },
    {
        "step_no": 2,
        "action": "Verify",
        "object_name": "Home",
        "input_value": "https://www.pmi.org",
        "locator_by": "",
        "locator_value": "",
        "expected": "Application opened",
    },
]

REGISTER_XPATH = (
    "//a[contains(normalize-space(.),'Register')] "
    "| //button[contains(normalize-space(.),'Register')] "
    "| //*[@role='link' or self::span or self::div]"
    "[contains(normalize-space(.),'Register')]/ancestor::a[1]"
)

LINK_STEPS = OPEN_STEPS + [
    {
        "step_no": 3,
        "action": "PerformClick",
        "object_name": "Register",
        "input_value": "",
        "locator_by": "xpath",
        "locator_value": REGISTER_XPATH,
        "expected": "Register",
    },
    {
        "step_no": 4,
        "action": "Verify",
        "object_name": "Register Page",
        "input_value": "Register",
        "locator_by": "",
        "locator_value": "",
        "expected": "Register page visible",
    },
]

app = create_app()
with app.app_context():
    project = db.session.get(Project, 9)
    if not project:
        raise SystemExit("project 9 missing")

    login = TestCase.query.filter_by(project_id=9, external_key="TC_AI_LOGIN").first()
    if login:
        login.external_key = "TC_AI_OPEN_APP"
        login.name = "[AI] Open application URL and verify"
        login.test_type = "automation"
        login.automation_steps = OPEN_STEPS
        print("updated", login.id, login.external_key)

    link = TestCase.query.filter_by(project_id=9, external_key="TC_AI_LINK_Register").first()
    if link:
        link.automation_steps = LINK_STEPS
        print("updated", link.id, link.external_key)

    project.status = "READY"
    db.session.commit()
    print("project status -> READY")
    print("DONE — re-run test cases 47/48 (now open-app + register link)")
