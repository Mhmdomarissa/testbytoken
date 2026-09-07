"""Import OpenAPI/Swagger and Postman collections into API Farm requests."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.parse import urljoin


def _new_id(prefix: str = "api") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _sample_for_schema(schema: dict[str, Any] | None) -> Any:
    if not schema or not isinstance(schema, dict):
        return "value"
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        out = {}
        for key, sub in props.items():
            if required and key not in required and len(out) >= 3:
                continue
            out[key] = _sample_for_schema(sub if isinstance(sub, dict) else {})
        return out or {"id": 1}
    if t == "array":
        return [_sample_for_schema(schema.get("items") if isinstance(schema.get("items"), dict) else {})]
    if t == "integer" or t == "number":
        return 1
    if t == "boolean":
        return True
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    return "string"


def _resolve_ref(doc: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        return {}
    cur: Any = doc
    for part in ref[2:].split("/"):
        cur = cur.get(part, {}) if isinstance(cur, dict) else {}
    return cur if isinstance(cur, dict) else {}


def _base_url_from_openapi(doc: dict) -> str:
    if doc.get("swagger") == "2.0":
        host = doc.get("host") or "localhost"
        base = doc.get("basePath") or ""
        schemes = doc.get("schemes") or ["https"]
        return f"{schemes[0]}://{host}{base}".rstrip("/")
    servers = doc.get("servers") or []
    if servers and isinstance(servers[0], dict):
        return str(servers[0].get("url") or "").rstrip("/")
    return ""


def import_openapi(doc: dict[str, Any], base_url_override: str = "") -> list[dict[str, Any]]:
    """Convert OpenAPI 3 / Swagger 2 document into API Farm request dicts."""
    base = (base_url_override or _base_url_from_openapi(doc)).rstrip("/")
    paths = doc.get("paths") or {}
    requests: list[dict[str, Any]] = []

    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            if not isinstance(op, dict):
                continue
            name = op.get("summary") or op.get("operationId") or f"{method.upper()} {path}"
            url_path = path
            # Replace path params with sample values
            for param in op.get("parameters") or []:
                if not isinstance(param, dict):
                    continue
                if "$ref" in param:
                    param = _resolve_ref(doc, param["$ref"])
                if param.get("in") == "path":
                    sample = param.get("example") or _sample_for_schema(param.get("schema") or {"type": "string"})
                    url_path = re.sub(rf"\{{{param.get('name')}\}}", str(sample), url_path)

            full_url = urljoin(base + "/", url_path.lstrip("/")) if base else url_path
            headers: dict[str, str] = {"Content-Type": "application/json"}
            body = ""

            # OpenAPI 3 requestBody
            rb = op.get("requestBody") or {}
            if isinstance(rb, dict) and "$ref" in rb:
                rb = _resolve_ref(doc, rb["$ref"])
            content = (rb.get("content") or {}) if isinstance(rb, dict) else {}
            schema = None
            if "application/json" in content:
                schema = (content["application/json"] or {}).get("schema")
            elif content:
                first = next(iter(content.values()), {})
                schema = first.get("schema") if isinstance(first, dict) else None
            if isinstance(schema, dict) and "$ref" in schema:
                schema = _resolve_ref(doc, schema["$ref"])
            if schema:
                body = json.dumps(_sample_for_schema(schema), indent=2)

            # Swagger 2 body param
            if not body:
                for param in op.get("parameters") or []:
                    if isinstance(param, dict) and param.get("in") == "body":
                        schema = param.get("schema") or {}
                        if "$ref" in schema:
                            schema = _resolve_ref(doc, schema["$ref"])
                        body = json.dumps(_sample_for_schema(schema), indent=2)

            # Success status from responses
            expected = 200
            responses = op.get("responses") or {}
            for code in ("200", "201", "204"):
                if code in responses:
                    expected = int(code)
                    break

            requests.append(
                {
                    "id": _new_id("oas"),
                    "name": str(name),
                    "method": method.upper(),
                    "url": full_url,
                    "headers": headers,
                    "body": body if method.upper() in {"POST", "PUT", "PATCH"} else "",
                    "expected_status": expected,
                    "assertions": [],
                    "tags": ["imported", "openapi", "positive"],
                    "auth": {"type": "none"},
                }
            )
    return requests


def _walk_postman_items(items: list, out: list[dict], folder: str = "") -> None:
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "Request")
        if "item" in item and isinstance(item["item"], list):
            _walk_postman_items(item["item"], out, f"{folder}/{name}" if folder else name)
            continue
        req = item.get("request")
        if not isinstance(req, dict):
            continue
        method = str(req.get("method") or "GET").upper()
        url_obj = req.get("url")
        if isinstance(url_obj, dict):
            raw = url_obj.get("raw")
            if raw:
                url = str(raw)
            else:
                host = ".".join(url_obj.get("host") or [])
                path = "/".join(url_obj.get("path") or [])
                protocol = url_obj.get("protocol") or "https"
                url = f"{protocol}://{host}/{path}".replace("///", "//")
        else:
            url = str(url_obj or "")

        headers: dict[str, str] = {}
        for h in req.get("header") or []:
            if isinstance(h, dict) and h.get("key") and not h.get("disabled"):
                headers[str(h["key"])] = str(h.get("value") or "")

        body = ""
        body_obj = req.get("body") or {}
        if isinstance(body_obj, dict):
            mode = body_obj.get("mode")
            if mode == "raw":
                body = str(body_obj.get("raw") or "")
            elif mode == "urlencoded":
                parts = []
                for row in body_obj.get("urlencoded") or []:
                    if isinstance(row, dict):
                        parts.append(f"{row.get('key')}={row.get('value')}")
                body = "&".join(parts)

        auth = {"type": "none"}
        auth_obj = req.get("auth") or item.get("auth")
        if isinstance(auth_obj, dict):
            atype = (auth_obj.get("type") or "").lower()
            if atype == "bearer":
                token = ""
                for row in auth_obj.get("bearer") or []:
                    if isinstance(row, dict) and row.get("key") == "token":
                        token = str(row.get("value") or "")
                auth = {"type": "bearer", "token": token}
            elif atype == "basic":
                user = pwd = ""
                for row in auth_obj.get("basic") or []:
                    if not isinstance(row, dict):
                        continue
                    if row.get("key") == "username":
                        user = str(row.get("value") or "")
                    if row.get("key") == "password":
                        pwd = str(row.get("value") or "")
                auth = {"type": "basic", "username": user, "password": pwd}

        full_name = f"{folder} / {name}" if folder else name
        out.append(
            {
                "id": _new_id("pm"),
                "name": full_name,
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "expected_status": 200,
                "assertions": [],
                "tags": ["imported", "postman", "positive"],
                "auth": auth,
            }
        )


def import_postman(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a Postman Collection v2.x export into API Farm requests."""
    info = doc.get("info") or {}
    items = doc.get("item") or []
    out: list[dict[str, Any]] = []
    _walk_postman_items(items, out)
    # stamp collection name into first tag note via name prefix already handled
    _ = info.get("name")
    return out


def detect_and_import(payload: dict[str, Any] | list, base_url: str = "") -> tuple[str, list[dict[str, Any]]]:
    """Auto-detect OpenAPI vs Postman and import."""
    if isinstance(payload, list):
        raise ValueError("Expected a JSON object (OpenAPI or Postman collection)")
    if payload.get("info") and (payload.get("item") is not None or "schema" in str(payload.get("info"))):
        # Postman collections have info.schema containing postman
        schema = str((payload.get("info") or {}).get("schema") or "")
        if "postman" in schema.lower() or payload.get("item") is not None:
            return "postman", import_postman(payload)
    if payload.get("openapi") or payload.get("swagger") or payload.get("paths"):
        return "openapi", import_openapi(payload, base_url_override=base_url)
    if payload.get("item") is not None:
        return "postman", import_postman(payload)
    raise ValueError("Unrecognized format. Provide OpenAPI/Swagger or Postman Collection v2 JSON.")
