"""Generate combined HTML report for manual + automation E2E tests."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from uts_engine.automation.base import RESULTS_DIR, TestResult

STYLES = """
:root { --navy: #1a2b4a; --green: #0a7a2f; --red: #b00020; --amber: #b8860b; --bg: #f5f7fb; }
body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: var(--bg); color: #222; }
h1 { color: var(--navy); margin-bottom: 4px; }
h2 { color: var(--navy); margin-top: 28px; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }
h3 { color: #334155; margin-top: 18px; }
.meta { color: #555; margin-bottom: 20px; }
.cards { display: flex; gap: 14px; flex-wrap: wrap; margin: 16px 0; }
.card { background: #fff; border-radius: 8px; padding: 14px 18px; min-width: 130px;
        box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.card h3 { margin: 0; font-size: 28px; }
.card span { font-size: 12px; color: #666; text-transform: uppercase; }
.pass { color: var(--green); font-weight: bold; }
.fail { color: var(--red); font-weight: bold; }
.manual { color: var(--amber); font-weight: bold; }
table { border-collapse: collapse; width: 100%; background: #fff;
        box-shadow: 0 2px 8px rgba(0,0,0,.08); font-size: 13px; margin-top: 10px; }
th, td { border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: var(--navy); color: #fff; }
tr:nth-child(even) { background: #f8fafc; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
.badge-auto { background: #dbeafe; color: #1e40af; }
.badge-manual { background: #fef3c7; color: #92400e; }
.log-box { background: #1e1e1e; color: #d4d4d4; padding: 14px; border-radius: 6px;
           font-family: Consolas, monospace; font-size: 12px; white-space: pre-wrap;
           max-height: 400px; overflow-y: auto; }
.exec-line { margin: 2px 0; }
.exec-step { color: #4fc3f7; }
.exec-pass { color: #81c784; }
.exec-fail { color: #e57373; }
.exec-run { color: #ffd54f; font-weight: bold; }
footer { margin-top: 30px; color: #888; font-size: 12px; }
.chart-row { display: flex; gap: 28px; flex-wrap: wrap; align-items: center; margin: 20px 0; }
.pie-chart {
  width: 180px; height: 180px; border-radius: 50%;
  box-shadow: 0 2px 12px rgba(0,0,0,.12);
  flex-shrink: 0;
}
.pie-empty {
  width: 180px; height: 180px; border-radius: 50%; background: #e2e8f0;
  display: flex; align-items: center; justify-content: center;
  color: #64748b; font-size: 13px;
}
.pie-legend { list-style: none; padding: 0; margin: 0; }
.pie-legend li { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 14px; }
.pie-legend .dot { width: 14px; height: 14px; border-radius: 3px; display: inline-block; }
.dot-pass { background: var(--green); }
.dot-fail { background: var(--red); }
.dot-manual { background: var(--amber); }
"""


def _status_class(status: str) -> str:
    return {"PASS": "pass", "FAIL": "fail", "MANUAL_PENDING": "manual"}.get(status, "")


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _pie_chart_html(pass_count: int, fail_count: int, manual_count: int = 0) -> str:
    total = pass_count + fail_count + manual_count
    if total == 0:
        return '<div class="pie-empty">No results</div>'
    pass_pct = round(pass_count / total * 100, 1)
    fail_pct = round(fail_count / total * 100, 1)
    manual_pct = round(100 - pass_pct - fail_pct, 1)
    pass_end = pass_pct
    fail_end = pass_end + fail_pct
    style = (
        f"background: conic-gradient("
        f"var(--green) 0% {pass_end}%, "
        f"var(--red) {pass_end}% {fail_end}%, "
        f"var(--amber) {fail_end}% 100%)"
    )
    legend = [
        f'<li><span class="dot dot-pass"></span> Pass: {pass_count} ({pass_pct}%)</li>',
        f'<li><span class="dot dot-fail"></span> Fail: {fail_count} ({fail_pct}%)</li>',
    ]
    if manual_count:
        legend.append(
            f'<li><span class="dot dot-manual"></span> Manual pending: {manual_count} ({manual_pct}%)</li>'
        )
    return (
        f'<div class="pie-chart" style="{style}" title="Pass/Fail distribution"></div>'
        f'<ul class="pie-legend">{"".join(legend)}</ul>'
    )


def _format_log_html(log_text: str) -> str:
    lines = []
    for line in log_text.splitlines():
        css = "exec-line"
        if ">>> EXECUTING:" in line:
            css += " exec-run"
        elif "| STEP" in line:
            css += " exec-step"
        elif "| PASS" in line:
            css += " exec-pass"
        elif "| FAIL" in line:
            css += " exec-fail"
        lines.append(f'<div class="{css}">{_esc(line)}</div>')
    return "\n".join(lines) if lines else "<div>No execution log captured.</div>"


def build_html(
    suite_name: str,
    environment: str,
    automation_results: list[TestResult],
    manual_scenarios: list[dict],
    execution_log: str,
    total_duration_ms: float,
    show_execution_log: bool = False,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    auto_pass = sum(1 for r in automation_results if r.status == "PASS")
    auto_fail = sum(1 for r in automation_results if r.status == "FAIL")
    total = len(manual_scenarios) + len(automation_results)
    duration_sec = round(total_duration_ms / 1000, 2)

    scenario_rows: list[str] = []
    idx = 1
    for s in manual_scenarios:
        scenario_rows.append(
            f"<tr><td>{idx}</td><td><strong>{_esc(s['id'])}</strong></td>"
            f"<td><span class='badge badge-manual'>MANUAL</span></td>"
            f"<td>{_esc(s['title'])}</td><td class='manual'>MANUAL_PENDING</td>"
            f"<td>—</td><td>—</td><td>Run manually: {_esc(s.get('file', ''))}</td></tr>"
        )
        idx += 1

    for result in automation_results:
        passed = sum(1 for s in result.steps if s.status == "PASS")
        sc = _status_class(result.status)
        scenario_rows.append(
            f"<tr><td>{idx}</td><td><strong>{_esc(result.tc_id)}</strong></td>"
            f"<td><span class='badge badge-auto'>AUTOMATION</span></td>"
            f"<td>{_esc(result.title)}</td><td class='{sc}'>{_esc(result.status)}</td>"
            f"<td>{passed}/{len(result.steps)}</td><td>{result.duration_ms:.0f} ms</td>"
            f"<td>{_esc(result.error or 'All steps passed')}</td></tr>"
        )
        idx += 1

    automation_sections: list[str] = []
    for result in automation_results:
        step_rows = []
        for step in result.steps:
            sc = _status_class(step.status)
            step_rows.append(
                f"<tr><td>{step.step_no}</td><td>{_esc(step.action)}</td>"
                f"<td>{_esc(step.object_name)}</td><td>{_esc(step.input_value)}</td>"
                f"<td class='{sc}'>{_esc(step.status)}</td><td>{_esc(step.message)}</td>"
                f"<td>{step.duration_ms}</td></tr>"
            )
        sc = _status_class(result.status)
        automation_sections.append(
            f"<h3>{_esc(result.tc_id)} — {_esc(result.title)} "
            f"<span class='{sc}'>[{_esc(result.status)}]</span></h3>"
            f"<table><tr><th>Step</th><th>Action</th><th>Object</th><th>Input</th>"
            f"<th>Status</th><th>Message</th><th>Time (ms)</th></tr>"
            + "".join(step_rows)
            + "</table>"
        )

    manual_rows = []
    for s in manual_scenarios:
        manual_rows.append(
            f"<tr><td><strong>{_esc(s['id'])}</strong></td>"
            f"<td>{_esc(s['title'])}</td><td><code>{_esc(s.get('file', ''))}</code></td>"
            f"<td class='manual'>MANUAL_PENDING</td></tr>"
        )

    manual_section = ""
    if manual_scenarios:
        manual_section = f"""
  <h2>Manual Test Cases (Execute &amp; Record Results)</h2>
  <table>
    <tr><th>TC ID</th><th>Title</th><th>File</th><th>Status</th></tr>
    {"".join(manual_rows)}
  </table>"""

    execution_section = ""
    if show_execution_log:
        execution_section = f"""
  <h2>What Was Executing During Automation</h2>
  <p>Live execution log captured during the automation run:</p>
  <div class="log-box">{_format_log_html(execution_log)}</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>UTS E2E Test Report</title>
  <style>{STYLES}</style>
</head>
<body>
  <h1>UTS E2E Test Report</h1>
  <div class="meta">
    <div><strong>Suite:</strong> {_esc(suite_name)}</div>
    <div><strong>Generated:</strong> {generated_at}</div>
    <div><strong>Environment:</strong> {_esc(environment)}</div>
  </div>

  <div class="cards">
    <div class="card"><span>Total Scenarios</span><h3>{total}</h3></div>
    <div class="card"><span>Automation Pass</span><h3 class="pass">{auto_pass}</h3></div>
    <div class="card"><span>Automation Fail</span><h3 class="fail">{auto_fail}</h3></div>
    <div class="card"><span>Manual Pending</span><h3 class="manual">{len(manual_scenarios)}</h3></div>
    <div class="card"><span>Duration</span><h3>{duration_sec}s</h3></div>
  </div>

  <h2>Pass / Fail Distribution</h2>
  <div class="chart-row">{_pie_chart_html(auto_pass, auto_fail, len(manual_scenarios))}</div>

  <h2>Scenario Summary</h2>
  <table>
    <tr><th>#</th><th>TC ID</th><th>Type</th><th>Title</th><th>Status</th>
        <th>Steps</th><th>Duration</th><th>Details</th></tr>
    {"".join(scenario_rows)}
  </table>

  <h2>Automation Step Details</h2>
  {"".join(automation_sections)}
{manual_section}
{execution_section}

  <footer>UTS E2E Test Suite — Report auto-generated</footer>
</body>
</html>"""


def write_html_report(
    automation_results: list[TestResult],
    manual_scenarios: list[dict],
    execution_log: str,
    suite_name: str,
    environment: str,
    total_duration_ms: float,
    show_execution_log: bool = False,
) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    html_content = build_html(
        suite_name, environment, automation_results, manual_scenarios,
        execution_log, total_duration_ms, show_execution_log=show_execution_log,
    )

    report_path = RESULTS_DIR / f"e2e-report-{timestamp}.html"
    latest_path = RESULTS_DIR / "latest-e2e-report.html"
    json_path = RESULTS_DIR / f"e2e-results-{timestamp}.json"

    report_path.write_text(html_content, encoding="utf-8")
    latest_path.write_text(html_content, encoding="utf-8")

    payload = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total": len(manual_scenarios) + len(automation_results),
            "auto_pass": sum(1 for r in automation_results if r.status == "PASS"),
            "auto_fail": sum(1 for r in automation_results if r.status == "FAIL"),
            "manual_pending": len(manual_scenarios),
            "duration_sec": round(total_duration_ms / 1000, 2),
        },
        "automation": [asdict(r) for r in automation_results],
        "manual": manual_scenarios,
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    return report_path
