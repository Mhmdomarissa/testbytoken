"""Build a portable UTS worker package zip for one-click install on user PCs."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "web-data",
    "reports",
    "generated",
    "__pycache__",
    ".cursor",
    "_dev_pkg_build",
    "node_modules",
    "agent-transcripts",
    ".pytest_cache",
    ".mypy_cache",
}

SKIP_FILE_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3"}
SKIP_FILE_NAMES = {".env", "worker.env", "worker-token.json"}


def _should_skip(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    if any(part in SKIP_DIR_NAMES for part in rel_parts[:-1]):
        return True
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix.lower() in SKIP_FILE_SUFFIXES:
        return True
    # Local deploy helpers / secrets
    if path.name.startswith("_deploy"):
        return True
    return False


def build_worker_package_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip(path):
                continue
            arc = path.relative_to(ROOT).as_posix()
            zf.write(path, arcname=f"UTS-Worker/{arc}")
    return buf.getvalue()
