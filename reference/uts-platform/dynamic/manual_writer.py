"""Write dynamic manual test case files from discovery result."""

from __future__ import annotations

from pathlib import Path

from dynamic.discovery import DiscoveryResult, ScenarioDef, StepDef

MANUAL_DIR = Path(__file__).resolve().parent.parent / "manual-tests"
GENERATED_DIR = Path(__file__).resolve().parent.parent / "generated"


def _manual_filename(scenario_id: str, title: str) -> str:
    slug = title.lower()
    slug = "".join(c if c.isalnum() else "_" for c in slug)[:40].strip("_")
    return f"{scenario_id}_{slug}.txt"


def _format_manual_case(scenario: ScenarioDef, discovery: DiscoveryResult) -> str:
    lines = [
        "=" * 80,
        f"TEST CASE: {scenario.id} — {scenario.title}",
        f"Type: MANUAL (auto-generated) | Source URL: {discovery.url}",
        "=" * 80,
        "",
        "Objective:",
        f"Validate {scenario.title.lower()} on {discovery.app_name}.",
        "",
        "Preconditions:",
        f"- Application URL is reachable: {discovery.url}",
        f"- Valid credentials: {discovery.username} / ********",
        "",
        "Test Data:",
        f"  URL:      {discovery.url}",
        f"  Username: {discovery.username}",
        f"  Password: ********",
        "",
        "-" * 80,
        f"{'Step':<6} {'Action':<16} {'Object':<24} {'Input/Expected':<30}",
        "-" * 80,
    ]
    for step in scenario.steps:
        detail = step.input_value or step.expected or ""
        lines.append(
            f"{step.step_no:<6} {step.action:<16} {step.object_name:<24} {detail:<30}"
        )
    lines.extend([
        "-" * 80,
        "",
        "Expected Result:",
        scenario.steps[-1].expected if scenario.steps else "All steps pass.",
        "",
        "Status: [ ] Pass  [ ] Fail  [ ] Blocked",
        "Tester: _______________   Date: _______________",
        "",
        f"Generated: {discovery.discovered_at}",
    ])
    return "\n".join(lines)


def write_manual_tests(discovery: DiscoveryResult) -> list[dict]:
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    manual_scenarios = []
    for scenario in discovery.scenarios:
        if scenario.type != "manual":
            continue
        filename = _manual_filename(scenario.id, scenario.title)
        rel_path = f"manual-tests/{filename}"
        full_path = MANUAL_DIR / filename
        content = _format_manual_case(scenario, discovery)
        full_path.write_text(content, encoding="utf-8")
        manual_scenarios.append({
            "id": scenario.id,
            "type": "manual",
            "title": scenario.title,
            "file": rel_path,
        })

    return manual_scenarios
