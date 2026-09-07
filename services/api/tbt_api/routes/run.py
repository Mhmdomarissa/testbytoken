"""POST /run — run the real browser test via the Playwright engine, return the trace.

Read-only checks only on the free path. No form submits, no writes. The hard
timeout is enforced inside engines/playwright_runner.py (Playwright timeouts).
"""

import os

from fastapi import APIRouter, HTTPException

from tbt_api.config import SHOTS_DIR, is_allowed_target, normalize_target
from tbt_api.engines.playwright_runner import run_test
from tbt_api.routes.plan import SUPPORTED_CHECKS
from tbt_api.schemas import RunRequest

router = APIRouter()


@router.post("/run")
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
