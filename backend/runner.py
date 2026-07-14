"""
runner.py — the test engine. This is the heart of the product.

It opens a REAL browser (Chromium via Playwright), drives it through a set of
checks against a target URL, and produces an auditable trace: every step, its
status, timing, a screenshot, a tamper-evident hash, and a compute-token cost.

This file was proven working in a live test against a real SPA. Claude Code
should wrap it behind an API endpoint (see app.py) — NOT rewrite it from scratch.

KEY LESSONS baked in (do not remove):
  - Wait for 'networkidle' + a short pause so single-page apps finish rendering.
    A plain DOM-load screenshot of an SPA is blank. This bit us; it's fixed here.
  - The target may redirect (e.g. an app sending you to /login). Record the final
    URL, don't assume you stayed on the URL you requested.
  - Two outputs per run: the auditable trace (customer value) and compute metrics
    (billing input). Keep them separate.
"""

import json, hashlib, time, datetime, os
from playwright.sync_api import sync_playwright

# In the real app this comes from the Chromium install path. Locally, Playwright
# manages it; on a server set PLAYWRIGHT_CHROMIUM_PATH or let Playwright resolve it.
CHROMIUM_PATH = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")  # None = let Playwright find it


def run_test(target_url: str, checks: list[str] | None = None, shots_dir: str = "./shots") -> dict:
    """
    Run a test against target_url.

    checks: list of check ids to run. Supported: "page_load", "title",
            "https", "login_present", "performance". Defaults to a safe read-only set.
    Returns: the full run dict (trace + metrics). Also writes screenshots to shots_dir.
    """
    if checks is None:
        checks = ["page_load", "title", "https", "login_present", "performance"]

    os.makedirs(shots_dir, exist_ok=True)
    now = datetime.datetime.now(datetime.UTC)

    run = {
        "run_id": "run_" + now.strftime("%Y%m%d%H%M%S"),
        "target": target_url,
        "engine": "Playwright / Chromium (real browser)",
        "started_utc": now.isoformat(),
        "steps": [],
    }

    def step(name, fn):
        s = {"name": name, "status": "pass", "detail": "", "ms": 0, "shot": None}
        t0 = time.time()
        try:
            s["detail"] = fn() or ""
        except Exception as e:
            s["status"] = "fail"
            s["detail"] = f"{type(e).__name__}: {e}"
        s["ms"] = int((time.time() - t0) * 1000)
        run["steps"].append(s)
        return s

    launch_kwargs = {"args": ["--no-sandbox"]}
    if CHROMIUM_PATH:
        launch_kwargs["executable_path"] = CHROMIUM_PATH

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page()

        if "page_load" in checks:
            def nav():
                r = page.goto(target_url, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(2000)  # let SPA hydrate — do not remove
                return f"HTTP {r.status}"
            s = step("Page loads + app renders", nav)
            s["shot"] = os.path.join(shots_dir, f"{run['run_id']}_load.png")
            try:
                page.screenshot(path=s["shot"], full_page=True)
            except Exception:
                s["shot"] = None

        if "title" in checks:
            def title_check():
                t = page.title()
                run["page_title"] = t
                assert len(t) > 0, "page returned an empty title"
                return f"title = '{t}'"
            step("Page has a title", title_check)

        if "https" in checks:
            def https_check():
                assert page.url.startswith("https://"), "final URL is not HTTPS"
                return f"served over HTTPS ({page.url})"
            step("Served over HTTPS", https_check)

        if "login_present" in checks:
            def login_present():
                body = page.locator("body").inner_text()[:500].lower()
                els = page.locator(
                    "input[type='password'], input[type='email'], "
                    "input[name*='user' i], input[name*='email' i], "
                    "button:has-text('Login'), a:has-text('Login'), "
                    "button:has-text('Sign in'), a:has-text('Sign in')"
                )
                n = els.count()
                kw = any(w in body for w in ["login", "sign in", "log in"])
                assert n > 0 or kw, "no login / auth entry point detected"
                return f"{n} auth element(s); keyword match={kw}"
            step("Login interface present", login_present)

        if "performance" in checks:
            def perf():
                t = page.evaluate(
                    "() => { const e = performance.getEntriesByType('navigation')[0];"
                    " return e ? Math.round(e.responseEnd) : null; }"
                )
                return f"responseEnd ~{t}ms" if t else "timing unavailable"
            step("Capture load performance", perf)

        browser.close()

    # --- finalize: verdict, hash (auditable), token cost (billing) ---
    run["finished_utc"] = datetime.datetime.now(datetime.UTC).isoformat()
    run["steps_passed"] = sum(1 for s in run["steps"] if s["status"] == "pass")
    run["steps_total"] = len(run["steps"])
    run["verdict"] = "PASS" if run["steps_passed"] == run["steps_total"] else "PARTIAL"

    trace_bytes = json.dumps(run["steps"], sort_keys=True).encode()
    run["trace_sha256"] = hashlib.sha256(trace_bytes).hexdigest()

    total_ms = sum(s["ms"] for s in run["steps"])
    run["compute_ms"] = total_ms
    run["test_tokens"] = max(1, round(total_ms / 100))  # crude meter — tune later

    return run


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    result = run_test(url)
    print(json.dumps(result, indent=2))
