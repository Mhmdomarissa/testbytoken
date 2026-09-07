"""API Test Farm — send HTTP requests and assert results."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
API_DATA_DIR = ROOT / "web-data" / "api-farm"


@dataclass
class ApiAssertion:
    kind: str  # status | json_path | body_contains | header
    expected: str
    path: str = ""  # for json_path / header name


@dataclass
class ApiRequestSpec:
    id: str
    name: str
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    expected_status: int = 200
    assertions: list[ApiAssertion] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def _parse_json_path(data: Any, path: str) -> Any:
    from api_farm.chain import parse_json_path

    return parse_json_path(data, path)


def apply_auth_headers(headers: dict[str, str] | None, auth: dict[str, Any] | None) -> dict[str, str]:
    """Merge Bearer / Basic auth into request headers."""
    import base64

    out = {k: str(v) for k, v in (headers or {}).items() if k}
    auth = auth or {}
    atype = str(auth.get("type") or "none").lower()
    if atype == "bearer":
        token = str(auth.get("token") or "").strip()
        if token:
            out["Authorization"] = f"Bearer {token}"
    elif atype == "basic":
        user = str(auth.get("username") or "")
        password = str(auth.get("password") or "")
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        out["Authorization"] = f"Basic {token}"
    elif atype == "apikey":
        header_name = str(auth.get("header") or "X-API-Key")
        value = str(auth.get("value") or "")
        if value:
            out[header_name] = value
    return out


def execute_http(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str = "",
    timeout: float = 30,
    auth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one HTTP call. Returns status, headers, body, duration_ms."""
    method = (method or "GET").upper().strip()
    hdrs = apply_auth_headers(headers, auth)
    data = None
    if body and method in {"POST", "PUT", "PATCH", "DELETE"}:
        data = body.encode("utf-8")
        lower_keys = {k.lower() for k in hdrs}
        if "content-type" not in lower_keys:
            hdrs.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
            duration_ms = (time.perf_counter() - started) * 1000
            text = raw.decode("utf-8", errors="replace")
            return {
                "ok": True,
                "http_status": resp.getcode(),
                "headers": dict(resp.headers.items()),
                "body": text,
                "duration_ms": round(duration_ms, 2),
                "error": "",
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        duration_ms = (time.perf_counter() - started) * 1000
        text = raw.decode("utf-8", errors="replace") if raw else str(exc)
        return {
            "ok": False,
            "http_status": exc.code,
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body": text,
            "duration_ms": round(duration_ms, 2),
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        duration_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "http_status": None,
            "headers": {},
            "body": "",
            "duration_ms": round(duration_ms, 2),
            "error": str(exc),
        }


def evaluate_assertions(
    response: dict[str, Any],
    expected_status: int | None = 200,
    assertions: list[ApiAssertion] | list[dict] | None = None,
) -> tuple[bool, list[str]]:
    messages: list[str] = []
    passed = True
    http_status = response.get("http_status")

    if expected_status is not None:
        if http_status != int(expected_status):
            passed = False
            messages.append(f"Expected status {expected_status}, got {http_status}")
        else:
            messages.append(f"Status {http_status} OK")

    body = response.get("body") or ""
    headers = {str(k).lower(): str(v) for k, v in (response.get("headers") or {}).items()}

    for item in assertions or []:
        if isinstance(item, dict):
            kind = item.get("kind", "")
            expected = str(item.get("expected", ""))
            path = str(item.get("path", ""))
            # Operator assertions are handled in chain.evaluate_operator_assertions
            if item.get("operator"):
                continue
        else:
            kind = item.kind
            expected = item.expected
            path = item.path

        if kind == "body_contains":
            if expected not in body:
                passed = False
                messages.append(f"Body missing text: {expected[:80]}")
            else:
                messages.append(f"Body contains '{expected[:40]}'")
        elif kind == "header" and not (isinstance(item, dict) and item.get("operator")):
            actual = headers.get(path.lower(), "")
            if expected.lower() not in actual.lower():
                passed = False
                messages.append(f"Header {path}: expected '{expected}', got '{actual}'")
            else:
                messages.append(f"Header {path} OK")
        elif kind == "json_path" and not (isinstance(item, dict) and item.get("operator")):
            try:
                data = json.loads(body) if body else None
                actual = _parse_json_path(data, path)
                if str(actual) != expected and expected not in str(actual):
                    passed = False
                    messages.append(f"JSON {path}: expected '{expected}', got '{actual}'")
                else:
                    messages.append(f"JSON {path} OK")
            except Exception as exc:  # noqa: BLE001
                passed = False
                messages.append(f"JSON path '{path}' failed: {exc}")
        elif kind == "status_class":
            cls = (expected or "2xx").lower()
            if http_status is None:
                passed = False
                messages.append(f"Expected {cls}, got no HTTP status")
            else:
                bucket = f"{http_status // 100}xx"
                if bucket != cls:
                    passed = False
                    messages.append(f"Expected {cls}, got {http_status}")
                else:
                    messages.append(f"Status class {cls} OK ({http_status})")

    if response.get("error") and http_status is None:
        passed = False
        messages.append(response["error"])

    return passed, messages


@dataclass
class ApiStepResult:
    name: str
    method: str
    url: str
    status: str  # PASS | FAIL
    http_status: int | None
    duration_ms: float
    message: str
    response_preview: str = ""
    extracted: dict[str, Any] = field(default_factory=dict)
    variables_snapshot: dict[str, Any] = field(default_factory=dict)


def run_api_request(
    spec: ApiRequestSpec | dict,
    variables: dict[str, Any] | None = None,
) -> ApiStepResult:
    from api_farm.chain import (
        evaluate_operator_assertions,
        extract_variables,
        prepare_request,
    )

    # Mutate caller's dict so suite chaining receives extracted values.
    if variables is None:
        variables = {}
    if isinstance(spec, dict):
        raw_spec = dict(spec)
    else:
        raw_spec = {
            "id": spec.id,
            "name": spec.name,
            "method": spec.method,
            "url": spec.url,
            "headers": spec.headers,
            "body": spec.body,
            "expected_status": spec.expected_status,
            "assertions": [
                asdict(a) if hasattr(a, "__dataclass_fields__") else a for a in spec.assertions
            ],
            "tags": spec.tags,
            "auth": {},
            "extractors": [],
        }

    prepared = prepare_request(raw_spec, variables)
    assertions = list(prepared.get("assertions") or [])
    auth = dict(prepared.get("auth") or {})
    use_status_class = any(
        isinstance(a, dict) and a.get("kind") == "status_class" for a in assertions
    )
    expected = None if use_status_class else int(prepared.get("expected_status") or 200)

    if str(auth.get("type") or "").lower() == "bearer":
        token_val = str(auth.get("token") or "")
        if "{{" in token_val and "}}" in token_val:
            messages_preflight: list[str] = []
            unresolved = re.findall(r"\{\{\s*([a-zA-Z0-9_.$-]+)\s*\}\}", token_val)
            missing = [name for name in unresolved if name not in variables]
            if missing:
                messages_preflight.append(
                    f"Bearer token not resolved ({', '.join(missing)}). "
                    "Run Login first with extractors, or save Login before this API in the suite."
                )
        else:
            messages_preflight = []
    else:
        messages_preflight = []

    response = execute_http(
        str(prepared.get("method") or "GET"),
        str(prepared.get("url") or ""),
        dict(prepared.get("headers") or {}),
        str(prepared.get("body") or ""),
        auth=auth,
    )
    ok, messages = evaluate_assertions(response, expected, assertions)
    messages = messages_preflight + messages
    op_ok, op_messages = evaluate_operator_assertions(response, assertions, variables)
    ok = ok and op_ok
    messages.extend(op_messages)

    extracted: dict[str, Any] = {}
    extract_always = bool(raw_spec.get("extract_on_fail"))
    if ok or extract_always or response.get("http_status"):
        extracted, extract_messages = extract_variables(
            response, raw_spec.get("extractors") or [], variables
        )
        messages.extend(extract_messages)

    http_status = response.get("http_status")
    if not ok and extracted and http_status and 200 <= int(http_status) < 300:
        expected_status = prepared.get("expected_status")
        if expected_status is not None and int(http_status) != int(expected_status):
            messages.append(
                f"Tip: API returned {http_status} but expected {expected_status}. "
                f"Token was still extracted — set Expected status to {http_status} for login APIs."
            )

    preview = (response.get("body") or "")[:500]
    return ApiStepResult(
        name=str(prepared.get("name") or raw_spec.get("name") or "API"),
        method=str(prepared.get("method") or "GET"),
        url=str(prepared.get("url") or ""),
        status="PASS" if ok else "FAIL",
        http_status=response.get("http_status"),
        duration_ms=float(response.get("duration_ms") or 0),
        message="; ".join(messages) if messages else ("OK" if ok else "Failed"),
        response_preview=preview,
        extracted={k: str(v) for k, v in extracted.items()},
        variables_snapshot={k: str(v) for k, v in variables.items()},
    )


def run_api_suite(
    specs: list[ApiRequestSpec | dict],
    initial_variables: dict[str, Any] | None = None,
    stop_on_fail: bool = False,
) -> dict[str, Any]:
    """Run requests in order, chaining extracted values into later requests."""
    variables = dict(initial_variables or {})
    results: list[ApiStepResult] = []
    for spec in specs:
        result = run_api_request(spec, variables)
        results.append(result)
        if result.status == "FAIL" and stop_on_fail:
            break
    passed = sum(1 for r in results if r.status == "PASS")
    failed = len(results) - passed
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
        },
        "variables": {k: str(v) for k, v in variables.items()},
        "results": [asdict(r) for r in results],
    }


def collection_path(project_key: str) -> Path:
    API_DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in project_key) or "default"
    return API_DATA_DIR / f"{safe}.json"


def load_collection(project_key: str) -> dict[str, Any]:
    path = collection_path(project_key)
    if not path.is_file():
        return {"name": project_key, "requests": [], "variables": {}}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data.setdefault("variables", {})
    data.setdefault("requests", [])
    return data


def save_collection(project_key: str, payload: dict[str, Any]) -> Path:
    path = collection_path(project_key)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def build_api_report_html(suite_name: str, suite: dict[str, Any]) -> str:
    summary = suite.get("summary") or {}
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    total = int(summary.get("total") or 0) or max(1, passed + failed)
    pass_pct = round(passed / total * 100, 1)
    fail_pct = round(100 - pass_pct, 1)
    rows = []
    for i, r in enumerate(suite.get("results") or [], 1):
        sc = "pass" if r.get("status") == "PASS" else "fail"
        rows.append(
            "<tr>"
            f"<td>{i}</td><td><strong>{_esc(r.get('name'))}</strong></td>"
            f"<td>{_esc(r.get('method'))}</td><td><code>{_esc(r.get('url'))}</code></td>"
            f"<td class='{sc}'>{_esc(r.get('status'))}</td>"
            f"<td>{_esc(r.get('http_status'))}</td>"
            f"<td>{_esc(r.get('duration_ms'))} ms</td>"
            f"<td>{_esc(r.get('message'))}"
            f"<div style='margin-top:4px;color:#555;font-size:11px'>extracted: {_esc(r.get('extracted') or {})}</div>"
            f"</td>"
            "</tr>"
        )
    pie = (
        f"background: conic-gradient(#0a7a2f 0% {pass_pct}%, #b00020 {pass_pct}% 100%)"
        if total
        else "background:#e2e8f0"
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>API Test Report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f5f7fb;color:#222}}
h1{{color:#1a2b4a}}.pass{{color:#0a7a2f;font-weight:bold}}.fail{{color:#b00020;font-weight:bold}}
.cards{{display:flex;gap:14px;flex-wrap:wrap}}.card{{background:#fff;padding:14px 18px;border-radius:8px;min-width:120px;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.pie{{width:160px;height:160px;border-radius:50%;{pie}}}
table{{border-collapse:collapse;width:100%;background:#fff;margin-top:16px}}
th,td{{border:1px solid #e2e8f0;padding:8px;text-align:left;font-size:13px;vertical-align:top}}
th{{background:#1a2b4a;color:#fff}}
</style></head><body>
<h1>UTS API Test Farm Report</h1>
<p><strong>Suite:</strong> {_esc(suite_name)} &nbsp;|&nbsp; <strong>Generated:</strong> {_esc(suite.get('generated_at'))}</p>
<div class="cards">
  <div class="card"><span>Total</span><h3>{total}</h3></div>
  <div class="card"><span>Pass</span><h3 class="pass">{passed}</h3></div>
  <div class="card"><span>Fail</span><h3 class="fail">{failed}</h3></div>
  <div class="pie" title="Pass/Fail"></div>
</div>
<table><tr><th>#</th><th>Name</th><th>Method</th><th>URL</th><th>Result</th><th>HTTP</th><th>Time</th><th>Details</th></tr>
{''.join(rows)}
</table>
</body></html>"""


def _esc(value: Any) -> str:
    import html

    return html.escape("" if value is None else str(value))
