"""POST /plan — map plain-English "what to test" + URL to a list of check ids.

Uses an LLM (Claude) to map free text to our supported checks. Quick-pick
buttons skip the LLM and map directly (cheaper, instant).
"""

import json
import os

import anthropic
from fastapi import APIRouter, HTTPException

from tbt_api.config import is_allowed_target, normalize_target
from tbt_api.schemas import PlanRequest

router = APIRouter()

SUPPORTED_CHECKS = [
    "page_load", "title", "https", "login_present", "performance",
    "links_work", "buttons_present",
]

# Human-readable one-liners for each check — fed to the LLM planner and reused
# in the keyword fallback so both paths agree on what each id means.
CHECK_DESCRIPTIONS = {
    "page_load": "the page loads and the app renders (HTTP status)",
    "title": "the page has a non-empty <title>",
    "https": "the site is served over HTTPS",
    "login_present": "a login / sign-in interface is present",
    "performance": "capture page load performance timing",
    "links_work": "every link on the page resolves (no broken/dead links)",
    "buttons_present": "buttons are present, visible and clickable",
}

# Quick-pick buttons -> direct mapping (no LLM call needed).
QUICK_PICKS = {
    "page_load": ["page_load", "title", "https", "performance"],
    "user_login": ["page_load", "login_present", "https"],
}

# Keyword fallback: map free text -> checks WITHOUT an LLM. This keeps the
# free-text box working even when ANTHROPIC_API_KEY isn't set, and is the safety
# net if the LLM call fails. Each entry is (check id, trigger words).
_KEYWORD_TRIGGERS = [
    ("links_work",     ["link", "href", "url", "navigat", "broken", "dead link", "anchor"]),
    ("buttons_present",["button", "click", "cta", "call to action", "press", "tap"]),
    ("login_present",  ["login", "log in", "sign in", "signin", "auth", "password", "account"]),
    ("https",          ["https", "ssl", "tls", "secure", "certificate", "encrypt"]),
    ("performance",    ["performance", "speed", "fast", "slow", "load time", "latency", "responsive time"]),
    ("title",          ["title", "heading", "headline", "meta"]),
]


def keyword_plan(description: str) -> list[str]:
    """Map a plain-English request to check ids using simple keyword matching.
    Always includes page_load as the baseline. Order is stable/deterministic."""
    d = description.lower()
    checks = ["page_load"]
    for check_id, words in _KEYWORD_TRIGGERS:
        if any(w in d for w in words):
            checks.append(check_id)
    # de-dupe, preserve order
    seen, out = set(), []
    for c in checks:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def llm_plan(description: str) -> list[str]:
    """Ask Claude to map free text to check ids. Raises if the key is missing or
    the API errors — callers fall back to keyword_plan()."""
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    catalog = "\n".join(f"- {cid}: {desc}" for cid, desc in CHECK_DESCRIPTIONS.items())
    system = (
        "You are a test planner. Map the user's plain-English website testing "
        "request to a set of check ids from the catalog below. "
        "Reply with ONLY a JSON array of ids, no prose.\n\n"
        f"Catalog:\n{catalog}\n\n"
        "Always include page_load. If unsure, add title as well."
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system=system,
        messages=[{"role": "user", "content": description}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    checks = json.loads(text)
    checks = [c for c in checks if c in SUPPORTED_CHECKS]
    if "page_load" not in checks:
        checks = ["page_load"] + checks
    return checks or ["page_load", "title"]


def drop_irrelevant_checks(checks: list[str], target: str) -> list[str]:
    """An http:// or file:// target can never pass the HTTPS check — planning it
    would just guarantee a failed step, so leave it out for those targets."""
    if not target.startswith("https://"):
        checks = [c for c in checks if c != "https"]
    return checks


@router.post("/plan")
def plan(req: PlanRequest):
    target = normalize_target(req.url)
    if not is_allowed_target(target):
        raise HTTPException(400, "That target isn't allowed on the free tier.")

    # Quick-pick path: instant, no LLM, no cost.
    if req.quick_pick:
        checks = QUICK_PICKS.get(req.quick_pick)
        if not checks:
            raise HTTPException(400, f"Unknown quick pick: {req.quick_pick}")
        return {"checks": drop_irrelevant_checks(checks, target), "target": target, "source": "quick_pick"}

    # Free-text path: turn the plain-English request into concrete checks.
    # Prefer the LLM when a key is configured, but ALWAYS fall back to keyword
    # mapping so the box works out of the box (and if the API call fails).
    if not req.description:
        raise HTTPException(400, "Provide a description or a quick_pick.")

    checks, source = None, "keyword"
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            checks = llm_plan(req.description)
            source = "llm"
        except Exception:
            checks = None  # fall through to keyword mapping
    if not checks:
        checks = keyword_plan(req.description)
        source = "keyword"
    return {"checks": drop_irrelevant_checks(checks, target), "target": target, "source": source}
