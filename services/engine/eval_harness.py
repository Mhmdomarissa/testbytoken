#!/usr/bin/env python3
"""Eval harness — Phase 0 honesty scorecard.

Not just pass/fail counts: how many verify steps actually carried a
checkable assertion, and how many steps ran against a real, crawl-observed
locator rather than none at all. Reads the two artifacts an engine-run
already writes — no new run mode, no extra instrumentation.

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


def build_scorecard(results: dict, discovered_flow: dict, commit: str | None = None) -> dict:
    step_lookup = _step_lookup(discovered_flow)
    has_flow_data = bool(step_lookup)

    test_cases = results.get("automation") or []
    steps_total = steps_pass = steps_fail = steps_skip = 0
    assertions_total = assertions_with_kind = 0
    steps_with_real_locator = 0

    for tc in test_cases:
        tc_id = tc.get("tc_id", "")
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

    honest_pass_rate = round(steps_pass / steps_total, 4) if steps_total else 0.0

    card = {
        "commit": commit if commit is not None else _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "test_cases": len(test_cases),
        "steps_total": steps_total,
        "steps_pass": steps_pass,
        "steps_fail": steps_fail,
        "steps_skip": steps_skip,
        "assertions_total": assertions_total,
        "assertions_with_kind": assertions_with_kind,
        "steps_with_real_locator": steps_with_real_locator,
        "honest_pass_rate": honest_pass_rate,
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
