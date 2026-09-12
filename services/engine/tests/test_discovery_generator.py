"""D7: discovery.py's own scenario generator now uses the same closed
assertion vocabulary as ai_brain.py (W3+W4) — this file locks in the parts
that are easy to silently regress: two step-copying helpers that
reconstruct a StepDef while renumbering it, and dropped the assertion
field because their field list predates that field existing on the
dataclass. Caught live: D7's url_matches fix appeared to do nothing in a
real run — TC_POS_03's Verify carried expected='http://...' but
assertion='' — traced to _with_login() silently stripping it on every
scenario it assembles.

No browser required.
"""

from __future__ import annotations

from uts_engine.discovery.discovery import StepDef, _build_negative_module_steps, _with_login


def test_with_login_preserves_assertion_field():
    login_base = [StepDef(1, "Navigate", "Application URL", "http://x", expected="loaded")]
    extra = [
        StepDef(
            1,
            "Verify",
            "Module Page",
            "",
            assertion="url_matches",
            expected="http://x/module",
        )
    ]

    combined = _with_login(login_base, extra)

    verify_steps = [s for s in combined if s.action == "Verify"]
    assert len(verify_steps) == 1
    assert verify_steps[0].assertion == "url_matches"
    assert verify_steps[0].expected == "http://x/module"


def test_with_login_renumbers_but_keeps_all_fields():
    login_base = [StepDef(1, "Navigate", "Application URL", "http://x")]
    extra = [
        StepDef(
            1,
            "Verify",
            "Thing",
            "in",
            "id",
            "thing-id",
            "exp",
            assertion="element_visible",
        )
    ]

    combined = _with_login(login_base, extra)

    assert combined[1].step_no == 2  # renumbered to follow login_base
    assert combined[1].locator_by == "id"
    assert combined[1].locator_value == "thing-id"
    assert combined[1].assertion == "element_visible"


def test_build_negative_module_steps_preserves_assertion_on_copied_steps():
    """positive_steps' own url_matches Verify (added ahead of any
    SetText/SetPassword/PerformSelect step) must survive being copied into
    the negative-flow steps, not just the click/nav steps around it."""
    positive_steps = [
        StepDef(1, "PerformClick", "Admin", "", "xpath", "//a", "Opened 'Admin' module"),
        StepDef(
            2,
            "Verify",
            "Admin Page",
            "",
            assertion="url_matches",
            expected="http://x/admin",
        ),
        StepDef(3, "SetText", "Username", "value", "id", "username", ""),
        StepDef(4, "PerformClick", "Save", "", "id", "save-btn", ""),
    ]

    neg_steps = _build_negative_module_steps(positive_steps, "Admin")

    verify_steps = [s for s in neg_steps if s.action == "Verify"]
    assert len(verify_steps) == 1
    assert verify_steps[0].assertion == "url_matches"
    assert verify_steps[0].expected == "http://x/admin"
