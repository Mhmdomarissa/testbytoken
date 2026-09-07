"""Download Windows embeddable Python 3.12 + pip into web-data/portable-python-win64.zip."""

from __future__ import annotations

import io
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web-data" / "portable-python-win64.zip"
PYTHON_VER = "3.12.10"
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VER}/python-{PYTHON_VER}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def prepare(force: bool = False) -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.is_file() and OUT.stat().st_size > 1_000_000 and not force:
        print(f"Already present: {OUT} ({OUT.stat().st_size} bytes)")
        return OUT

    with tempfile.TemporaryDirectory(prefix="uts-py-") as tmp:
        tmp_path = Path(tmp)
        embed_zip = tmp_path / "embed.zip"
        runtime = tmp_path / "runtime"
        runtime.mkdir()

        print(f"Downloading {EMBED_URL}")
        urllib.request.urlretrieve(EMBED_URL, embed_zip)  # noqa: S310
        with zipfile.ZipFile(embed_zip, "r") as zf:
            zf.extractall(runtime)

        # Enable site-packages for pip
        pth_files = list(runtime.glob("python*._pth"))
        if not pth_files:
            raise RuntimeError("python*._pth not found in embeddable package")
        pth = pth_files[0]
        text = pth.read_text(encoding="utf-8")
        text = text.replace("#import site", "import site")
        if "import site" not in text:
            text += "\nimport site\n"
        if "Lib\\site-packages" not in text and "Lib/site-packages" not in text:
            text = "Lib\\site-packages\n" + text
        pth.write_text(text, encoding="utf-8")

        get_pip = tmp_path / "get-pip.py"
        print(f"Downloading {GET_PIP_URL}")
        urllib.request.urlretrieve(GET_PIP_URL, get_pip)  # noqa: S310

        import subprocess

        py = runtime / "python.exe"
        print("Installing pip into embeddable runtime...")
        subprocess.run([str(py), str(get_pip), "--no-warn-script-location"], check=True)

        # Ensure pip module works: python -m pip
        subprocess.run([str(py), "-m", "pip", "--version"], check=True)

        print(f"Writing {OUT}")
        if OUT.exists():
            OUT.unlink()
        with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in runtime.rglob("*"):
                if path.is_file():
                    zf.write(path, arcname=f"runtime/{path.relative_to(runtime).as_posix()}")
        print(f"Done: {OUT} ({OUT.stat().st_size} bytes)")
        return OUT


if __name__ == "__main__":
    prepare(force="--force" in __import__("sys").argv)
