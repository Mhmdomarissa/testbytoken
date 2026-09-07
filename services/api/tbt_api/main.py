"""main.py — the API control plane. Wires config, routes and engines together.

Two Playwright-backed endpoints (routes/plan.py, routes/run.py):
  POST /plan  -> takes plain-English "what to test" + URL, returns a list of check ids.
  POST /run   -> takes URL + check ids, runs the real browser test, returns the trace.

Plus the signed-in UTS journey (routes/uts.py) — see docs/UTS_INTEGRATION_PLAN.md
for which engine serves the anonymous front page; that decision is deliberately
left open, so this module does not couple itself to either engine directly.

See tbt_api/config.py for the security guardrails (target allowlisting, local
demo mode) — they are product guarantees, not style preferences.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tbt_api.config import SHOTS_DIR
from tbt_api.routes.plan import router as plan_router
from tbt_api.routes.run import router as run_router
from tbt_api.routes.uts import router as uts_router

app = FastAPI(title="TaaS demo backend")

# In production, lock this down to your real frontend origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(plan_router)
app.include_router(run_router)
# The signed-in journey — a UTS engine per user. The anonymous homepage still
# runs the Playwright checks above; which engine serves the front page is a
# decision deliberately left open (see docs/UTS_INTEGRATION_PLAN.md).
app.include_router(uts_router)


@app.on_event("shutdown")
def _stop_workspaces():
    from tbt_api.engines.base import UtsEngine

    UtsEngine().shutdown_all()

# Screenshots: the runner writes PNGs here; we expose them read-only at /shots so
# the frontend can display them. Ensure the dir exists before mounting.
os.makedirs(SHOTS_DIR, exist_ok=True)
app.mount("/shots", StaticFiles(directory=SHOTS_DIR), name="shots")


@app.get("/health")
def health():
    return {"ok": True}
