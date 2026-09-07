"""Install UTS worker into the Windows Startup folder (auto-start at logon)."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORTCUT_NAME = "UTS-Worker-Auto.lnk"
RUNNER = ROOT / "RUN-WORKER-AUTO.bat"


def ensure_windows_autostart() -> str:
    """
    Create/update a Startup-folder shortcut so the worker starts at Windows login.
    Returns the shortcut path, or "" if skipped / failed.
    """
    if platform.system().lower() != "windows":
        return ""
    if not RUNNER.is_file():
        return ""

    ps = f"""
$ErrorActionPreference = 'Stop'
$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup '{SHORTCUT_NAME}'
$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut($lnkPath)
$s.TargetPath = r'{RUNNER}'
$s.WorkingDirectory = r'{ROOT}'
$s.WindowStyle = 7
$s.Description = 'UTS Worker Agent (auto-start)'
$s.Save()
Write-Output $lnkPath
"""
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        path = (completed.stdout or "").strip().splitlines()
        return path[-1].strip() if path else ""
    except Exception:  # noqa: BLE001
        return ""
