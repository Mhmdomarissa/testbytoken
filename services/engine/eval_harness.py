#!/usr/bin/env python3
"""Eval harness — Phase 0 honesty scorecard.

Not just pass/fail counts: how many verify steps actually carried a
checkable assertion, and how many steps ran against a real, crawl-observed
locator rather than none at all. Reads the two artifacts an engine-run
already writes — no new run mode, no extra instrumentation.

Split by generator (ai_brain.py vs discovery.py's own generator — see
_generator_of()) because a blended, whole-suite ratio is misleading once
W5/D1 started merging both generators' scenarios into the same run:
ai_brain.py is the one Phase 0 actually taught to emit real assertions
(W3+W4); discovery.py's own generator was not touched (see D7 in
docs/DEAD_CODE_INVENTORY.md) and its Verify steps still carry no assertion
kind. A single blended percentage averages a fixed generator with a known-
still-broken one and reports neither honestly.

Also reports two distinct pass rates rather than one unitless number:
case_pass_rate (test cases that passed outright) and step_pass_rate
(individual steps that passed) — these do not have to agree, and printing
only one invites reading it as the other.

Reads:
    generated/discovered-flow.json  — step-level assertion/locator source
                                       of truth (StepDef, as actually run)
    reports/e2e-results-*.json      — the latest run's per-step status

Writes (with --out): a single scorecard JSON. Prints to stdout regardless.

Usage:
    .venv/bin/python eval_harness.py --out ../../docs/evals/after.json
    .venv/bin/python eval_harness.py --results /path/to/e2e-results.json \
        --discovered-flow /path/to/discovered-flow.json --out before.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ENGINE_ROOT / "generated"
REPORTS_DIR = ENGINE_ROOT / "reports"

# ai_brain.py's generator (services/engine/uts_engine/planning/ai_brain.py)
# prefixes every scenario id it emits with "TC_AI_" — every call site does,
# with no exception (checked: _login_steps, _module_flow_scenarios and
# offline_understand's other branches). discovery.py's own generator never
# uses that prefix (TC_AUTO_*, TC_POS_*, TC_NEG_*, ...). This is a real,
# consistently-followed convention in the current code, not incidental —
# but it IS a naming-convention match, not a recorded field, so it silently
# breaks if either generator's prefix ever changes. There is currently no
# other signal in discovered-flow.json to classify a scenario's origin by.
_AI_BRAIN_PREFIX = "TC_AI_"


def _generator_of(tc_id: str) -> str:
    return "ai_brain" if tc_id.startswith(_AI_BRAIN_PREFIX) else "discovery_generator"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ENGINE_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _latest_results_file() -> Path | None:
    candidates = sorted(REPORTS_DIR.glob("e2e-results-*.json"))
    return candidates[-1] if candidates else None


def _step_lookup(discovered_flow: dict) -> dict[tuple[str, int], dict]:
    """(tc_id, step_no) -> raw StepDef dict, from discovered-flow.json."""
    lookup: dict[tuple[str, int], dict] = {}
    for scenario in discovered_flow.get("scenarios") or []:
        tc_id = scenario.get("id", "")
        for step in scenario.get("steps") or []:
            lookup[(tc_id, step.get("step_no"))] = step
    return lookup


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _score_test_cases(test_cases: list[dict], step_lookup: dict[tuple[str, int], dict]) -> dict:
    """Metrics for exactly the test cases passed in — the caller decides
    which subset (all of them, or one generator's)."""
    steps_total = steps_pass = steps_fail = steps_skip = 0
    assertions_total = assertions_with_kind = 0
    steps_with_real_locator = 0
    cases_passed = 0

    for tc in test_cases:
        tc_id = tc.get("tc_id", "")
        if (tc.get("status") or "").upper() == "PASS":
            cases_passed += 1
        for step in tc.get("steps") or []:
            steps_total += 1
            status = (step.get("status") or "").upper()
            if status == "PASS":
                steps_pass += 1
            elif status == "FAIL":
                steps_fail += 1
            elif status == "SKIP":
                steps_skip += 1

            action = (step.get("action") or "").lower()
            step_def = step_lookup.get((tc_id, step.get("step_no")))

            if action == "verify":
                assertions_total += 1
                if step_def and (step_def.get("assertion") or "").strip():
                    assertions_with_kind += 1

            if step_def and step_def.get("locator_by") and step_def.get("locator_value"):
                steps_with_real_locator += 1

    return {
        "test_cases": len(test_cases),
        "case_pass_rate": _rate(cases_passed, len(test_cases)),
        "steps_total": steps_total,
        "steps_pass": steps_pass,
        "steps_fail": steps_fail,
        "steps_skip": steps_skip,
        "step_pass_rate": _rate(steps_pass, steps_total),
        "assertions_total": assertions_total,
        "assertions_with_kind": assertions_with_kind,
        "assertion_kind_rate": _rate(assertions_with_kind, assertions_total),
        "steps_with_real_locator": steps_with_real_locator,
        "locator_rate": _rate(steps_with_real_locator, steps_total),
    }


def build_scorecard(results: dict, discovered_flow: dict, commit: str | None = None) -> dict:
    step_lookup = _step_lookup(discovered_flow)
    has_flow_data = bool(step_lookup)

    test_cases = results.get("automation") or []
    by_generator_cases: dict[str, list[dict]] = {"ai_brain": [], "discovery_generator": []}
    for tc in test_cases:
        by_generator_cases[_generator_of(tc.get("tc_id", ""))].append(tc)

    card = {
        "commit": commit if commit is not None else _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **_score_test_cases(test_cases, step_lookup),
        "by_generator": {
            name: _score_test_cases(cases, step_lookup)
            for name, cases in by_generator_cases.items()
        },
    }
    if not has_flow_data:
        card["note"] = (
            "no discovered-flow.json provided — assertions_with_kind and "
            "steps_with_real_locator are computed against an empty lookup "
            "(0 by construction), not a measured absence"
        )
    return card


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="Write scorecard JSON here too")
    parser.add_argument("--results", type=Path, default=None, help="Specific e2e-results-*.json (default: latest under reports/)")
    parser.add_argument("--discovered-flow", type=Path, default=None, help="Specific discovered-flow.json (default: generated/discovered-flow.json)")
    parser.add_argument("--commit", type=str, default=None, help="Override the commit field (for scoring an artifact from a different checkout)")
    args = parser.parse_args()

    results_path = args.results or _latest_results_file()
    if results_path is None or not results_path.is_file():
        print("No e2e-results-*.json found — run `make engine-run` first, or pass --results.", file=sys.stderr)
        return 1

    flow_path = args.discovered_flow or (GENERATED_DIR / "discovered-flow.json")
    discovered_flow = json.loads(flow_path.read_text(encoding="utf-8-sig")) if flow_path.is_file() else {}
    results = json.loads(results_path.read_text(encoding="utf-8-sig"))

    scorecard = build_scorecard(results, discovered_flow, commit=args.commit)
    text = json.dumps(scorecard, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
