"""Start the local UTS web platform."""

from __future__ import annotations

import os
import time
import webbrowser
from threading import Thread
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import load_dotenv

from webapp import create_app


load_dotenv()
app = create_app()


def _open_when_ready(url: str) -> None:
    """Open the browser only after the local server accepts connections."""
    for _ in range(60):
        try:
            with urlopen(url, timeout=1):
                webbrowser.open(url)
                return
        except (URLError, OSError):
            time.sleep(0.5)
    webbrowser.open(url)


if __name__ == "__main__":
    host = os.getenv("UTS_HOST", "0.0.0.0")
    port = int(os.getenv("UTS_PORT", "5050"))
    network_ips = [
        value.strip()
        for value in os.getenv("UTS_NETWORK_IPS", "").split(",")
        if value.strip()
    ]
    public_urls = [f"http://{ip}:{port}" for ip in network_ips]
    if not public_urls:
        public_urls = [
            os.getenv("UTS_PUBLIC_URL", f"http://127.0.0.1:{port}").rstrip("/")
        ]
    browser_url = os.getenv("UTS_BROWSER_URL", f"http://127.0.0.1:{port}").rstrip("/")
    if os.getenv("UTS_OPEN_BROWSER", "true").lower() == "true":
        Thread(target=_open_when_ready, args=(browser_url,), daemon=True).start()
    print(f"Local URL:   http://127.0.0.1:{port}")
    for index, public_url in enumerate(public_urls, start=1):
        print(f"Network {index}:   {public_url}")
    app.run(host=host, port=port, debug=False, threaded=True)
