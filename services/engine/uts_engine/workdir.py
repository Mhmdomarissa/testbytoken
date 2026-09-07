"""Per-user data root for the engine.

The engine ships its own code — config/, templates/, the demo app — and that is
shared and read-only. Everything a run *produces* (generated/, reports/, logs/,
ALM and Xpedite exports) is written under ``UTS_WORKDIR`` instead, so that one
engine per user cannot overwrite another user's run.

Unset, this resolves to the engine directory, which is the original
single-user-on-one-checkout behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path

# services/engine/, i.e. one level above the uts_engine/ package this file lives in.
ENGINE_ROOT = Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Directory this process writes its run artifacts into."""
    raw = (os.environ.get("UTS_WORKDIR") or "").strip()
    root = Path(raw).expanduser().resolve() if raw else ENGINE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root
