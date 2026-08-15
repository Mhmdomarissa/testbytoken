"""Generate positive and negative API test variants."""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _break_json_body(body: str) -> str:
    text = (body or "").strip()
    if not text:
        return '{"__invalid": true}'
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text + "@@@INVALID"
    if isinstance(data, dict):
        if data:
            # remove first required-looking field / blank a string
            key = next(iter(data))
            if isinstance(data[key], str):
                data[key] = ""
            elif isinstance(data[key], (int, float)):
                data[key] = -1
            else:
                data.pop(key, None)
            data["__neg"] = "invalid"
        else:
            data = {"__invalid": True}
        return json.dumps(data, indent=2)
    if isinstance(data, list):
        return "[]"
    return '{"__invalid": true}'


def generate_positive_negative(base: dict[str, Any]) -> list[dict[str, Any]]:
    """From one request, produce positive + negative auto cases."""
    pos = copy.deepcopy(base)
    pos["id"] = _new_id("pos")
    pos["name"] = f"[POS] {base.get('name') or 'API'}"
    pos["tags"] = list({*(base.get("tags") or []), "positive", "auto"})
    pos["expected_status"] = int(base.get("expected_status") or 200)
    if not pos.get("assertions"):
        pos["assertions"] = []

    neg = copy.deepcopy(base)
    neg["id"] = _new_id("neg")
    neg["name"] = f"[NEG] {base.get('name') or 'API'}"
    neg["tags"] = list({*(base.get("tags") or []), "negative", "auto"})
    method = str(base.get("method") or "GET").upper()

    if method in {"POST", "PUT", "PATCH"}:
        neg["body"] = _break_json_body(str(base.get("body") or ""))
        neg["expected_status"] = 400
        neg["assertions"] = [
            {"kind": "status_class", "expected": "4xx", "path": ""},
        ]
    else:
        # Negative GET: strip auth / use bad token / hit bad path
        url = str(base.get("url") or "").rstrip("/")
        neg["url"] = f"{url}/__invalid_resource_{uuid.uuid4().hex[:6]}"
        neg["expected_status"] = 404
        auth = dict(base.get("auth") or {})
        if auth.get("type") == "bearer":
            neg["auth"] = {"type": "bearer", "token": "INVALID_TOKEN"}
            neg["expected_status"] = 401
            neg["name"] = f"[NEG] {base.get('name') or 'API'} (bad token)"
        elif auth.get("type") == "basic":
            neg["auth"] = {"type": "basic", "username": "bad", "password": "bad"}
            neg["expected_status"] = 401
            neg["name"] = f"[NEG] {base.get('name') or 'API'} (bad basic auth)"

    return [pos, neg]


def expand_collection_with_pos_neg(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each non-auto request, append POS/NEG variants (keep originals too)."""
    expanded: list[dict[str, Any]] = []
    for req in requests:
        tags = {t.lower() for t in (req.get("tags") or [])}
        if "auto" in tags and ("positive" in tags or "negative" in tags):
            expanded.append(req)
            continue
        expanded.append(req)
        expanded.extend(generate_positive_negative(req))
    return expanded
