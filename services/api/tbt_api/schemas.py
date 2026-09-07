"""schemas.py — Pydantic request models for the control-plane (Playwright) routes.

The UTS routes (routes/uts.py) keep their own request models locally — they are
not shared here to avoid a name collision (both sides have a RunRequest, shaped
differently: this one is url + checks, the UTS one is session_id + url + modules).
"""

from pydantic import BaseModel


class PlanRequest(BaseModel):
    url: str
    description: str | None = None
    quick_pick: str | None = None  # "page_load" | "user_login" | None


class RunRequest(BaseModel):
    url: str
    checks: list[str]
