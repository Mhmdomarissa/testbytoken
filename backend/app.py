"""
app.py — the API layer. Wraps runner.py behind HTTP so the frontend can call it.

Two endpoints:
  POST /plan  -> takes plain-English "what to test" + URL, returns a list of check ids.
                 Uses an LLM (Claude) to map free text to our supported checks.
                 Quick-pick buttons skip the LLM and map directly (cheaper, instant).
  POST /run   -> takes URL + check ids, runs the real browser test, returns the trace.

SECURITY GUARDRAILS (MVP — keep these, they are not optional):
  - ALLOWLIST or sandbox only for the free tier. Right now we hard-block obvious
    private / internal targets. A stranger must not be able to point us at
    internal infra (DDoS-by-proxy). See is_allowed_target().
  - Read-only checks only on the free path. No form submits, no writes.
  - Hard timeout is enforced inside runner.py (Playwright timeouts).
  - NO CREDENTIALS over this API in plaintext. Login-gated testing comes later via
    a secrets vault (see docs/CREDENTIALS.md). Do not add a password field here.
"""

import os
import ipaddress
import pathlib
import re
import urllib.parse
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import anthropic

from runner import run_test
from uts_routes import router as uts_router

app = FastAPI(title="TaaS demo backend")

# In production, lock this down to your real frontend origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# The signed-in journey — a UTS engine per user. The anonymous homepage still
# runs the Playwright checks below; which engine serves the front page is a
# decision deliberately left open (see docs/UTS_INTEGRATION_PLAN.md).
app.include_router(uts_router)


@app.on_event("shutdown")
def _stop_workspaces():
    from workspaces import manager

    manager.shutdown_all()

# Screenshots: the runner writes PNGs here; we expose them read-only at /shots so
# the frontend can display them. Ensure the dir exists before mounting.
SHOTS_DIR = os.environ.get("SHOTS_DIR", "./shots")
os.makedirs(SHOTS_DIR, exist_ok=True)
app.mount("/shots", StaticFiles(directory=SHOTS_DIR), name="shots")

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
    import json
    checks = json.loads(text)
    checks = [c for c in checks if c in SUPPORTED_CHECKS]
    if "page_load" not in checks:
        checks = ["page_load"] + checks
    return checks or ["page_load", "title"]


class PlanRequest(BaseModel):
    url: str
    description: str | None = None
    quick_pick: str | None = None  # "page_load" | "user_login" | None


class RunRequest(BaseModel):
    url: str
    checks: list[str]


# LOCAL DEMO MODE: when on (the default), target restrictions are lifted so you
# can test anything from your own laptop — localhost, private IPs, even local
# HTML files (C:\path\to\page.html). Set TAAS_LOCAL_DEMO=0 before ANY public
# deployment; that re-enables is_allowed_target() and blocks file:// targets.
LOCAL_DEMO = os.environ.get("TAAS_LOCAL_DEMO", "1") == "1"

_WINDOWS_PATH = re.compile(r"^[a-zA-Z]:[\\/]")


def normalize_target(url: str) -> str:
    """Turn whatever the user pasted into something a browser can navigate to:
    a Windows file path becomes a file:/// URL, a bare domain gets https://."""
    url = url.strip().strip('"')
    if _WINDOWS_PATH.match(url):
        return pathlib.Path(url).as_uri()
    if url.startswith("file://"):
        return url
    if "://" not in url:
        return "https://" + url
    return url


def is_allowed_target(url: str) -> bool:
    """Block private/internal hosts on the free tier. Crude but essential.
    Bypassed entirely in LOCAL_DEMO mode (single-laptop demo)."""
    if LOCAL_DEMO:
        return True
    if url.startswith("file://"):
        return False
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    if not host:
        return False
    # block localhost-ish
    if host in ("localhost",) or host.endswith(".local"):
        return False
    # block raw private IPs
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        pass  # it's a hostname, not an IP — fine
    return True


def drop_irrelevant_checks(checks: list[str], target: str) -> list[str]:
    """An http:// or file:// target can never pass the HTTPS check — planning it
    would just guarantee a failed step, so leave it out for those targets."""
    if not target.startswith("https://"):
        checks = [c for c in checks if c != "https"]
    return checks


@app.post("/plan")
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


@app.post("/run")
def run(req: RunRequest):
    target = normalize_target(req.url)
    if not is_allowed_target(target):
        raise HTTPException(400, "That target isn't allowed on the free tier.")
    checks = [c for c in req.checks if c in SUPPORTED_CHECKS]
    if not checks:
        raise HTTPException(400, "No valid checks requested.")
    result = run_test(target, checks=checks, shots_dir=SHOTS_DIR)

    # Expose each captured screenshot as a servable URL. We add this AFTER the
    # runner has hashed the trace, so the auditable hash stays over the raw steps.
    for s in result.get("steps", []):
        shot_path = s.get("shot")
        if shot_path:
            s["shot_url"] = "/shots/" + os.path.basename(shot_path)
    return result


@app.get("/health")
def health():
    return {"ok": True}
