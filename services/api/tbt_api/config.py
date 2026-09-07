"""config.py — environment configuration and the free-tier target guardrail.

SECURITY GUARDRAILS (MVP — keep these, they are not optional):
  - ALLOWLIST or sandbox only for the free tier. Right now we hard-block obvious
    private / internal targets. A stranger must not be able to point us at
    internal infra (DDoS-by-proxy). See is_allowed_target().
  - NO CREDENTIALS over this API in plaintext. Login-gated testing comes later via
    a secrets vault (see docs/CREDENTIALS.md). Do not add a password field here.
"""

import ipaddress
import os
import pathlib
import re
import urllib.parse

# LOCAL DEMO MODE: when on (the default), target restrictions are lifted so you
# can test anything from your own laptop — localhost, private IPs, even local
# HTML files (C:\path\to\page.html). Set TAAS_LOCAL_DEMO=0 before ANY public
# deployment; that re-enables is_allowed_target() and blocks file:// targets.
LOCAL_DEMO = os.environ.get("TAAS_LOCAL_DEMO", "1") == "1"

# Screenshots: the runner writes PNGs here; served read-only at /shots so the
# frontend can display them.
SHOTS_DIR = os.environ.get("SHOTS_DIR", "./shots")

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
