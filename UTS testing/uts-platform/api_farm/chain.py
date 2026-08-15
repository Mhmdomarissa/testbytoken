"""Parametrization, operators, timestamps, and response-value chaining."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any


VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.$-]+)\s*\}\}")

OPERATORS = (
    "eq",
    "ne",
    "contains",
    "not_contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "regex",
    "exists",
    "not_exists",
)


def parse_json_path(data: Any, path: str) -> Any:
    """Very small JSON path: a.b[0].c"""
    cur = data
    for part in path.replace("[", ".").replace("]", "").split("."):
        if not part:
            continue
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(path)
    return cur


def builtin_variables() -> dict[str, str]:
    now = datetime.now(timezone.utc)
    local = datetime.now()
    return {
        "timestamp": str(int(local.timestamp())),
        "timestamp_ms": str(int(local.timestamp() * 1000)),
        "timestamp_utc": str(int(now.timestamp())),
        "date": local.strftime("%Y-%m-%d"),
        "datetime": local.strftime("%Y-%m-%dT%H:%M:%S"),
        "datetime_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uuid": str(uuid.uuid4()),
        "guid": str(uuid.uuid4()),
    }


def resolve_value(text: str, variables: dict[str, Any] | None = None) -> str:
    """Replace {{var}} placeholders. Built-ins: timestamp, date, datetime, uuid."""
    if text is None:
        return ""
    raw = str(text)
    if "{{" not in raw:
        return raw
    merged: dict[str, Any] = {}
    merged.update(builtin_variables())
    merged.update({str(k): v for k, v in (variables or {}).items()})

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in merged and merged[key] is not None:
            return str(merged[key])
        # nested path into a JSON-looking var is not supported here
        return match.group(0)

    # Resolve repeatedly so {{a}} that expands to something with {{b}} works once
    out = raw
    for _ in range(5):
        nxt = VAR_PATTERN.sub(_repl, out)
        if nxt == out:
            break
        out = nxt
    return out


def resolve_mapping(data: dict[str, Any] | None, variables: dict[str, Any] | None) -> dict[str, str]:
    return {str(k): resolve_value(str(v), variables) for k, v in (data or {}).items()}


def resolve_auth(auth: dict[str, Any] | None, variables: dict[str, Any] | None) -> dict[str, Any]:
    auth = dict(auth or {})
    out: dict[str, Any] = {"type": auth.get("type") or "none"}
    for key in ("token", "username", "password", "header", "value"):
        if key in auth:
            out[key] = resolve_value(str(auth.get(key) or ""), variables)
    return out


def apply_operator(actual: Any, operator: str, expected: str) -> tuple[bool, str]:
    op = (operator or "eq").lower().strip()
    actual_s = "" if actual is None else str(actual)
    expected_s = "" if expected is None else str(expected)

    if op == "exists":
        ok = actual is not None and actual_s != ""
        return ok, f"exists → {ok}"
    if op == "not_exists":
        ok = actual is None or actual_s == ""
        return ok, f"not_exists → {ok}"
    if op == "eq":
        ok = actual_s == expected_s
        return ok, f"{actual_s!r} eq {expected_s!r} → {ok}"
    if op == "ne":
        ok = actual_s != expected_s
        return ok, f"{actual_s!r} ne {expected_s!r} → {ok}"
    if op == "contains":
        ok = expected_s in actual_s
        return ok, f"{actual_s[:60]!r} contains {expected_s!r} → {ok}"
    if op == "not_contains":
        ok = expected_s not in actual_s
        return ok, f"not_contains {expected_s!r} → {ok}"
    if op == "regex":
        try:
            ok = bool(re.search(expected_s, actual_s))
        except re.error as exc:
            return False, f"regex error: {exc}"
        return ok, f"regex /{expected_s}/ → {ok}"

    # numeric comparisons
    if op in {"gt", "gte", "lt", "lte"}:
        try:
            a = float(actual_s)
            b = float(expected_s)
        except (TypeError, ValueError):
            return False, f"numeric compare failed: {actual_s!r} {op} {expected_s!r}"
        mapping = {
            "gt": a > b,
            "gte": a >= b,
            "lt": a < b,
            "lte": a <= b,
        }
        ok = mapping[op]
        return ok, f"{a} {op} {b} → {ok}"

    return False, f"unknown operator: {op}"


def evaluate_operator_assertions(
    response: dict[str, Any],
    assertions: list[dict[str, Any]] | None,
    variables: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Assertions with operators: kind=json_path|body|header|status + operator."""
    messages: list[str] = []
    passed = True
    body = response.get("body") or ""
    headers = {str(k).lower(): str(v) for k, v in (response.get("headers") or {}).items()}
    http_status = response.get("http_status")
    json_data = None
    try:
        json_data = json.loads(body) if body.strip().startswith(("{", "[")) else None
    except json.JSONDecodeError:
        json_data = None

    for item in assertions or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "json_path")
        # Skip legacy kinds handled elsewhere unless operator present
        operator = str(item.get("operator") or "").strip()
        if not operator and kind in {
            "body_contains",
            "status_class",
            "json_path",
            "header",
        }:
            # allow json_path without operator → eq
            if kind == "json_path":
                operator = "eq"
            elif kind == "body_contains":
                continue
            elif kind == "header" and not item.get("operator"):
                continue
            else:
                continue

        path = resolve_value(str(item.get("path") or ""), variables)
        expected = resolve_value(str(item.get("expected") or ""), variables)
        operator = operator or "eq"

        actual: Any = None
        try:
            if kind in {"json_path", "json"}:
                if json_data is None:
                    raise ValueError("response is not JSON")
                actual = parse_json_path(json_data, path) if path else json_data
            elif kind in {"body", "body_text"}:
                actual = body
            elif kind == "header":
                actual = headers.get(path.lower(), "")
            elif kind == "status":
                actual = http_status
            else:
                # treat as json path by default when operator given
                if json_data is None:
                    raise ValueError("response is not JSON")
                actual = parse_json_path(json_data, path) if path else json_data
        except Exception as exc:  # noqa: BLE001
            passed = False
            messages.append(f"Operator assert failed ({kind} {path}): {exc}")
            continue

        ok, detail = apply_operator(actual, operator, expected)
        label = f"{kind}:{path or '(root)'} {operator}"
        if ok:
            messages.append(f"PASS {label} — {detail}")
        else:
            passed = False
            messages.append(f"FAIL {label} — {detail}")

    return passed, messages


TOKEN_FIELD_PATHS = (
    "access_token",
    "accessToken",
    "token",
    "data.access_token",
    "data.accessToken",
    "data.token",
)


def _extract_one(
    response: dict[str, Any],
    ext: dict[str, Any],
    body: str,
    headers: dict[str, str],
    json_data: Any,
) -> tuple[str, Any]:
    name = str(ext.get("name") or ext.get("var") or "").strip()
    path = str(ext.get("path") or "").strip()
    source = str(ext.get("source") or "json").lower()
    if not name or not path:
        raise ValueError("extractor requires name and path")

    if source == "header":
        value = headers.get(path.lower(), "")
    elif source == "status":
        value = response.get("http_status")
    elif source == "body":
        value = body
    else:
        if json_data is None:
            raise ValueError("response is not JSON")
        value = parse_json_path(json_data, path)
    if value is None or value == "":
        raise ValueError(f"path {path!r} is empty")
    return name, value


def extract_variables(
    response: dict[str, Any],
    extractors: list[dict[str, Any]] | None,
    variables: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """
    Extract values from first/successful response into variables for later APIs.

    Extractor examples:
      {"name": "token", "path": "access_token"}
      {"name": "token", "path": "data.token", "source": "json"}
      {"name": "userId", "path": "id", "source": "json"}
      {"name": "reqId", "path": "X-Request-Id", "source": "header"}
    """
    extracted: dict[str, Any] = {}
    messages: list[str] = []
    body = response.get("body") or ""
    headers = {str(k).lower(): str(v) for k, v in (response.get("headers") or {}).items()}
    json_data = None
    try:
        json_data = json.loads(body) if body.strip().startswith(("{", "[")) else None
    except json.JSONDecodeError:
        json_data = None

    configured = [e for e in (extractors or []) if isinstance(e, dict)]
    for ext in configured:
        name = str(ext.get("name") or ext.get("var") or "").strip()
        path = str(ext.get("path") or "").strip()
        try:
            var_name, value = _extract_one(response, ext, body, headers, json_data)
            variables[var_name] = value
            extracted[var_name] = value
            messages.append(f"Extracted {var_name} from {path}")
        except Exception as exc:  # noqa: BLE001
            # Try common token field names when login returns access_token etc.
            if json_data is not None and name.lower() in {"token", "access_token", "accesstoken"}:
                for alt in TOKEN_FIELD_PATHS:
                    if alt == path:
                        continue
                    try:
                        value = parse_json_path(json_data, alt)
                        if value:
                            variables[name] = value
                            extracted[name] = value
                            messages.append(f"Extracted {name} from fallback path {alt}")
                            break
                    except Exception:  # noqa: BLE001
                        continue
                else:
                    messages.append(f"Extract failed for {name} at {path}: {exc}")
            else:
                messages.append(f"Extract failed for {name or path}: {exc}")

    return extracted, messages


def prepare_request(spec: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the request with {{params}} and timestamps resolved."""
    prepared = dict(spec)
    prepared["url"] = resolve_value(str(spec.get("url") or ""), variables)
    prepared["body"] = resolve_value(str(spec.get("body") or ""), variables)
    prepared["headers"] = resolve_mapping(spec.get("headers") or {}, variables)
    prepared["auth"] = resolve_auth(spec.get("auth") or {}, variables)
    # resolve assertion expected/path too
    assertions = []
    for a in spec.get("assertions") or []:
        if isinstance(a, dict):
            assertions.append(
                {
                    **a,
                    "path": resolve_value(str(a.get("path") or ""), variables),
                    "expected": resolve_value(str(a.get("expected") or ""), variables),
                }
            )
        else:
            assertions.append(a)
    prepared["assertions"] = assertions
    return prepared
