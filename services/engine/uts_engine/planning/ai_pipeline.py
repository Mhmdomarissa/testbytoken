"""
Apply AI understanding onto discovery: BDD features, object repo, TestData, scenarios.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from uts_engine.planning.ai_brain import load_ai_config, understand_application
from uts_engine.discovery.discovery import DiscoveryResult, ScenarioDef, StepDef
from uts_engine.workdir import data_root

# services/engine/, two levels above this file (uts_engine/planning/).
ROOT = Path(__file__).resolve().parent.parent.parent
GENERATED_DIR = data_root() / "generated"
BDD_DIR = GENERATED_DIR / "bdd"
AI_PLAN_FILE = GENERATED_DIR / "ai-plan.json"
OBJECT_REPO_FILE = GENERATED_DIR / "object-repository.json"
TESTDATA_FILE = GENERATED_DIR / "AI_TestData.xlsx"


def _ensure_dirs() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    BDD_DIR.mkdir(parents=True, exist_ok=True)


def _step_from_dict(raw: dict[str, Any]) -> StepDef:
    return StepDef(
        step_no=int(raw.get("step_no") or 0),
        action=str(raw.get("action") or "Verify"),
        object_name=str(raw.get("object_name") or ""),
        input_value=str(raw.get("input_value") or ""),
        locator_by=str(raw.get("locator_by") or ""),
        locator_value=str(raw.get("locator_value") or ""),
        expected=str(raw.get("expected") or ""),
        assertion=str(raw.get("assertion") or ""),
    )


def _resolve_placeholders(value: str, row: dict[str, Any]) -> str:
    if not value or "{{" not in value:
        return value

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key in row:
            return str(row[key])
        # case-insensitive
        for k, v in row.items():
            if str(k).lower() == key.lower():
                return str(v)
        return match.group(0)

    return re.sub(r"\{\{\s*([^}]+)\s*\}\}", repl, value)


def write_bdd_features(plan: dict[str, Any]) -> list[Path]:
    _ensure_dirs()
    written: list[Path] = []
    by_feature: dict[str, list[dict]] = {}
    for sc in plan.get("scenarios") or []:
        bdd = sc.get("bdd") or {}
        feature = bdd.get("feature") or sc.get("module") or "Application"
        by_feature.setdefault(feature, []).append(sc)

    for feature, scenarios in by_feature.items():
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", feature).strip("_") or "Feature"
        path = BDD_DIR / f"{safe}.feature"
        lines = [f"Feature: {feature}", ""]
        for sc in scenarios:
            bdd = sc.get("bdd") or {}
            title = bdd.get("scenario") or sc.get("title") or sc.get("id")
            lines.append(f"  Scenario: {title}")
            lines.append(f"    Given {bdd.get('given') or 'the application is available'}")
            lines.append(f"    When {bdd.get('when') or 'the user performs the steps'}")
            lines.append(f"    Then {bdd.get('then') or 'the expected result is verified'}")
            # Data-driven outline
            rows = sc.get("data_rows") or []
            if rows:
                keys = list(rows[0].keys())
                lines.append("")
                lines.append(f"  Scenario Outline: {title} (data-driven)")
                lines.append(f"    Given {bdd.get('given') or 'the application is available'}")
                lines.append(f"    When {bdd.get('when') or 'the user enters <' + keys[0] + '>'}")
                lines.append(f"    Then {bdd.get('then') or 'the expected result is verified'}")
                lines.append("    Examples:")
                lines.append("      | " + " | ".join(keys) + " |")
                for row in rows:
                    lines.append("      | " + " | ".join(str(row.get(k, "")) for k in keys) + " |")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        written.append(path)
    return written


def write_object_repository(objects: list[dict[str, Any]]) -> Path:
    _ensure_dirs()
    OBJECT_REPO_FILE.write_text(json.dumps(objects, indent=2, ensure_ascii=False), encoding="utf-8")
    return OBJECT_REPO_FILE


def write_testdata_workbook(plan: dict[str, Any]) -> Path | None:
    _ensure_dirs()
    sheets: dict[str, list[dict[str, Any]]] = {}
    for sc in plan.get("scenarios") or []:
        rows = sc.get("data_rows") or []
        if not rows:
            continue
        name = (sc.get("data_sheet") or sc.get("id") or "Data")[:31]
        sheets[name] = rows
    if not sheets:
        return None
    wb = Workbook()
    # remove default
    default = wb.active
    wb.remove(default)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row.get(h, "") for h in headers])
    wb.save(TESTDATA_FILE)
    return TESTDATA_FILE


def expand_data_driven_scenarios(scenarios: list[dict[str, Any]]) -> list[ScenarioDef]:
    """Turn AI scenarios (+ data rows) into executable ScenarioDef list."""
    out: list[ScenarioDef] = []
    for sc in scenarios:
        rows = sc.get("data_rows") or []
        base_id = sc.get("id") or "TC_AI"
        base_title = sc.get("title") or base_id
        module = sc.get("module") or ""
        sc_type = sc.get("type") or "automation"
        raw_steps = sc.get("steps") or []

        if not rows:
            steps = [_step_from_dict(st) for st in raw_steps]
            for i, st in enumerate(steps, start=1):
                st.step_no = i
            out.append(
                ScenarioDef(
                    id=str(base_id),
                    type=sc_type,
                    title=str(base_title),
                    steps=steps,
                    module=module,
                )
            )
            continue

        for idx, row in enumerate(rows, start=1):
            steps: list[StepDef] = []
            for st in raw_steps:
                step = _step_from_dict(st)
                step.input_value = _resolve_placeholders(step.input_value, row)
                step.expected = _resolve_placeholders(step.expected, row)
                steps.append(step)
            for i, st in enumerate(steps, start=1):
                st.step_no = i
            out.append(
                ScenarioDef(
                    id=f"{base_id}_D{idx}",
                    type=sc_type,
                    title=f"{base_title} [Data {idx}]",
                    steps=steps,
                    module=module,
                )
            )
    return out


def apply_ai_plan_to_discovery(
    discovery: DiscoveryResult,
    page_map: dict[str, Any] | None,
    modules: list[str],
    username: str,
    replace_scenarios: bool = False,
) -> dict[str, Any]:
    """
    Run AI understand, write artifacts, merge scenarios into discovery.
    Returns the AI plan dict.
    """
    _ensure_dirs()
    cfg = load_ai_config()
    discovery_dict = discovery.to_dict()
    plan = understand_application(
        discovery_dict,
        page_map=page_map,
        modules=modules,
        username=username,
        cfg=cfg,
    )

    AI_PLAN_FILE.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    if cfg.get("generate_object_repo", True):
        write_object_repository(plan.get("objects") or [])
    if cfg.get("generate_bdd", True):
        write_bdd_features(plan)
    if cfg.get("generate_data_driven", True):
        write_testdata_workbook(plan)

    ai_scenarios = expand_data_driven_scenarios(plan.get("scenarios") or [])
    if replace_scenarios:
        # Keep any pure login from discovery only if AI did not emit login
        discovery.scenarios = ai_scenarios
    else:
        discovery.scenarios.extend(ai_scenarios)

    # Merge objects into locators for runner
    for obj in plan.get("objects") or []:
        name = obj.get("name") or ""
        if not name:
            continue
        key = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower() or name
        if key not in discovery.locators and obj.get("locator_value"):
            discovery.locators[key] = {
                "by": obj.get("locator_by") or "xpath",
                "value": obj.get("locator_value") or "",
            }

    return plan
