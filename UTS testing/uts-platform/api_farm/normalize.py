"""Normalize API request fields pasted from Postman or other tools."""

from __future__ import annotations

import json
import re
from typing import Any

METHOD_ONLY = re.compile(
    r"^\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+",
    re.IGNORECASE,
)
HEADER_IN_URL = re.compile(
    r"^(https?://.+?)(Content-Type\s*:\s*[^\{]+)(\{.*)$",
    re.IGNORECASE | re.DOTALL,
)
JSON_BODY_START = re.compile(r"(\{.*|\[.*)", re.DOTALL)

COMMON_TOKEN_PATHS = (
    "access_token",
    "accessToken",
    "token",
    "data.access_token",
    "data.accessToken",
    "data.token",
    "result.token",
)


def parse_postman_paste(text: str) -> dict[str, Any] | None:
    """
    Parse a single-line Postman-style paste into method, url, headers, body.

    Example:
      POST https://api.example.com/loginContent-Type: application/json{"email":"a@b.com"}
    """
    raw = (text or "").strip()
    if not raw:
        return None

    method = ""
    url = raw
    headers: dict[str, str] = {}
    body = ""

    remainder = raw
    mm = METHOD_ONLY.match(raw)
    if mm:
        method = mm.group(1).upper()
        remainder = raw[mm.end() :].strip()
        url = remainder

    hm = HEADER_IN_URL.match(remainder)
    if hm:
        url = hm.group(1)
        header_blob = hm.group(2).strip()
        body = hm.group(3).strip()
        for line in re.split(r"[\r\n]+", header_blob):
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip()] = val.strip()
    elif "Content-Type:" in remainder.lower():
        idx = remainder.lower().find("content-type:")
        if idx > 0:
            prefix = remainder[:idx]
            rest = remainder[idx:]
            ct_end = rest.find("{")
            if ct_end == -1:
                ct_end = rest.find("[")
            if ct_end > 0:
                header_line = rest[:ct_end].strip()
                body = rest[ct_end:].strip()
                url = prefix.rstrip("/")
                if ":" in header_line:
                    key, val = header_line.split(":", 1)
                    headers[key.strip()] = val.strip()

    if not body:
        bm = JSON_BODY_START.search(raw)
        if bm and bm.start() > 0:
            possible = raw[: bm.start()].strip()
            if METHOD_ONLY.match(possible):
                possible = raw[METHOD_ONLY.match(possible).end() : bm.start()].strip()
            if possible.startswith("http") or HEADER_IN_URL.match(possible):
                body = bm.group(1).strip()
                if HEADER_IN_URL.match(possible):
                    hm2 = HEADER_IN_URL.match(possible)
                    assert hm2 is not None
                    url = hm2.group(1)
                    header_blob = hm2.group(2).strip()
                    for line in re.split(r"[\r\n]+", header_blob):
                        if ":" in line:
                            key, val = line.split(":", 1)
                            headers.setdefault(key.strip(), val.strip())
                else:
                    url = possible.split("Content-Type")[0].rstrip("/") if "Content-Type" in possible else possible

    if method or headers or body:
        return {
            "method": method or "POST",
            "url": url,
            "headers": headers,
            "body": body,
        }
    return None


def normalize_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Fix common paste mistakes in URL/body/headers before sending."""
    out = dict(payload)
    url = str(out.get("url") or "").strip()
    body = str(out.get("body") or "").strip()
    method = str(out.get("method") or "GET").upper()
    headers = dict(out.get("headers") or {})

    parsed = parse_postman_paste(url) or (parse_postman_paste(body) if body and body[0] not in "{[" else None)
    if parsed:
        if parsed.get("method"):
            method = parsed["method"]
        if parsed.get("url"):
            url = parsed["url"]
        if parsed.get("body") and not body.startswith(("{", "[")):
            body = parsed["body"]
        for k, v in (parsed.get("headers") or {}).items():
            headers.setdefault(k, v)

    if body.startswith(("{", "[")):
        try:
            json.loads(body)
        except json.JSONDecodeError:
            # Strip accidental prefix before JSON object
            bm = JSON_BODY_START.search(body)
            if bm:
                body = bm.group(1)

    out["method"] = method
    out["url"] = url
    out["body"] = body
    out["headers"] = headers
    return out


def suggest_token_extractors(extractors: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Default token extractor when user configures bearer chain but forgot extractors."""
    if extractors:
        return list(extractors)
    return [{"name": "token", "path": path, "source": "json"} for path in COMMON_TOKEN_PATHS[:1]]
