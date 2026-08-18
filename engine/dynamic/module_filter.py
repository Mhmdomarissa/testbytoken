"""Parse app-input description → module filter for targeted TC generation."""

from __future__ import annotations

import re


def parse_module_from_description(description: str | None) -> str:
    """
    Extract module name from description text.

    Examples:
      "Create Lead module test cases" → "Create Lead"
      "Admin module testing"          → "Admin"
      "Orders"                        → "Orders"
      "" / None                       → ""  (full application flow)
    """
    text = (description or "").strip()
    if not text:
        return ""

    m = re.search(
        r"^\s*(.+?)\s+module(?:\s+(?:test\s*cases?|testing|tests?))?\s*$",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(" -–—:")

    m = re.search(
        r"(?:test\s*cases?|testing|tests?)\s+(?:for\s+)?(.+)$",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(" -–—:")

    return text


def module_keywords(module: str) -> list[str]:
    if not module:
        return []
    words = [w for w in re.split(r"[\s_/.\-]+", module) if len(w) > 2]
    keys = [module.strip()]
    keys.extend(words)
    seen = set()
    out = []
    for k in keys:
        low = k.lower()
        if low not in seen:
            seen.add(low)
            out.append(k)
    return out


def matches_module(text: str, module: str) -> bool:
    if not module:
        return True
    blob = (text or "").lower()
    if not blob:
        return False
    for key in module_keywords(module):
        if key.lower() in blob:
            return True
    return False


def business_flow_bc_name(
    component: str = "",
    description: str = "",
    scenario_name: str = "",
    fallback: str = "Business_Flow",
) -> str:
    raw = (
        component
        or parse_module_from_description(description)
        or description
        or scenario_name
        or fallback
    )
    raw = re.sub(
        r"\b(module\s+)?(test\s*cases?|testing|tests?)\b",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip(" -–—:_")
    clean = re.sub(r"[^a-zA-Z0-9_ ]", "", str(raw).replace("-", "_"))
    name = clean.strip().replace(" ", "_") or fallback
    return name[:60]


def slugify_module(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "").strip()).strip("_").lower()
    return s[:40] or "module"
