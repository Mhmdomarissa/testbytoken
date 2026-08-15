"""Selenium WebDriver session — shared across automation tests."""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions

from automation.base import CONFIG_DIR, LOGS_DIR

logger = logging.getLogger(__name__)

DEMO_APP = Path(__file__).resolve().parent.parent / "demo-app"
_config: dict[str, Any] | None = None
_driver: webdriver.Remote | None = None
_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None
WDM_LOCK = Path.home() / ".wdm" / ".wdm-lock-chromedriver-win64"


def load_selenium_config() -> dict[str, Any]:
    global _config
    if _config is None:
        path = CONFIG_DIR / "selenium.json"
        _config = json.loads(path.read_text(encoding="utf-8"))
    return _config


def is_selenium_enabled() -> bool:
    return load_selenium_config().get("enabled", True)


def _start_demo_server(port: int) -> str:
    global _server, _server_thread
    if _server is not None:
        return f"http://127.0.0.1:{port}/index.html"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(DEMO_APP), **kwargs)

        def log_message(self, format, *args):  # noqa: A003
            pass

    _server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()
    return f"http://127.0.0.1:{port}/index.html"


def resolve_base_url() -> str:
    cfg = load_selenium_config()
    base = (cfg.get("base_url") or "demo").strip()
    if base.lower() == "demo":
        port = int(cfg.get("demo_port", 8765))
        return _start_demo_server(port)
    return base.rstrip("/")


def _clear_wdm_lock() -> None:
    """Remove stale webdriver-manager lock left by interrupted runs."""
    try:
        if WDM_LOCK.exists():
            WDM_LOCK.unlink()
    except OSError:
        pass


def _apply_network_options(options: Any, cfg: dict[str, Any]) -> None:
    """Make an automation profile reach internal hosts like the user's own browser.

    A fresh Selenium profile enables DNS-over-HTTPS and ignores profile-level PAC
    settings, so corporate/UAT hostnames fail with ERR_NAME_NOT_RESOLVED even when
    the same URL opens manually.
    """
    if cfg.get("disable_secure_dns", True):
        options.add_argument("--disable-features=DnsOverHttps")
        options.add_argument("--dns-over-https-mode=off")

    pac_url = (cfg.get("proxy_pac_url") or "").strip()
    if pac_url:
        options.add_argument(f"--proxy-pac-url={pac_url}")

    user_data_dir = (cfg.get("user_data_dir") or "").strip()
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument(f"--profile-directory={cfg.get('profile_directory') or 'Default'}")


def _stability_args(cfg: dict[str, Any]) -> list[str]:
    """Browser flags that reduce Chrome/Edge 'renderer timeout' failures."""
    args = [
        "--window-size=1280,900",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-ipc-flooding-protection",
        "--disable-features=TranslateUI,BlinkGenPropertyTrees,AutomationControlled",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-first-run",
        "--password-store=basic",
        "--use-mock-keychain",
        "--remote-allow-origins=*",
    ]
    if cfg.get("headless"):
        args.append("--headless=new")
    return args


def _page_load_strategy(cfg: dict[str, Any]) -> str:
    # eager = DOM interactive is enough; avoids hanging on slow trackers/ads
    strategy = str(cfg.get("page_load_strategy") or "eager").strip().lower()
    return strategy if strategy in {"normal", "eager", "none"} else "eager"


def _apply_timeouts(driver: webdriver.Remote, cfg: dict[str, Any]) -> None:
    driver.implicitly_wait(int(cfg.get("implicit_wait_seconds", 5)))
    driver.set_page_load_timeout(int(cfg.get("page_load_timeout_seconds", 90)))
    driver.set_script_timeout(int(cfg.get("script_timeout_seconds", 60)))


def _build_chrome_options(cfg: dict[str, Any]) -> ChromeOptions:
    options = ChromeOptions()
    options.page_load_strategy = _page_load_strategy(cfg)
    for arg in _stability_args(cfg):
        options.add_argument(arg)
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    if cfg.get("block_images"):
        prefs["profile.managed_default_content_settings.images"] = 2
    options.add_experimental_option("prefs", prefs)
    _apply_network_options(options, cfg)
    return options


def _create_chrome_driver(cfg: dict[str, Any]) -> webdriver.Chrome:
    options = _build_chrome_options(cfg)

    # Prefer Selenium Manager (built into Selenium 4.6+) — no wdm lock issues
    try:
        return webdriver.Chrome(options=options)
    except Exception:  # noqa: BLE001
        pass

    # Fallback: webdriver-manager with stale lock cleanup
    _clear_wdm_lock()
    try:
        from webdriver_manager.chrome import ChromeDriverManager

        for attempt in range(3):
            try:
                service = ChromeService(ChromeDriverManager().install())
                return webdriver.Chrome(service=service, options=options)
            except TimeoutError:
                _clear_wdm_lock()
                time.sleep(1.5 * (attempt + 1))
    except Exception:  # noqa: BLE001
        pass

    raise RuntimeError(
        "Chrome browser could not start. Close other Chrome/automation runs, "
        "then retry. If needed, install Google Chrome and update Selenium."
    )


def set_browser(browser: str) -> None:
    """Set browser for the next local session (web-dashboard project setting)."""
    cfg = load_selenium_config()
    cfg["browser"] = (browser or "chrome").strip().lower()


def _create_edge_driver(cfg: dict[str, Any]) -> webdriver.Edge:
    options = EdgeOptions()
    options.page_load_strategy = _page_load_strategy(cfg)
    for arg in _stability_args(cfg):
        options.add_argument(arg)
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    _apply_network_options(options, cfg)
    return webdriver.Edge(options=options)


def _create_firefox_driver(cfg: dict[str, Any]) -> webdriver.Firefox:
    options = FirefoxOptions()
    options.page_load_strategy = _page_load_strategy(cfg)
    if cfg.get("headless"):
        options.add_argument("-headless")
    options.add_argument("--width=1280")
    options.add_argument("--height=900")
    return webdriver.Firefox(options=options)


def create_driver() -> webdriver.Remote:
    cfg = load_selenium_config()
    browser = str(cfg.get("browser") or "chrome").lower()
    if browser == "edge":
        driver = _create_edge_driver(cfg)
    elif browser == "firefox":
        driver = _create_firefox_driver(cfg)
    else:
        driver = _create_chrome_driver(cfg)
    _apply_timeouts(driver, cfg)
    return driver


def _is_renderer_timeout(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "timed out receiving message from renderer" in text
        or "timeout: timed out receiving message" in text
        or "page load timeout" in text
        or isinstance(exc, TimeoutException)
    )


def _stop_loading(driver: webdriver.Remote) -> None:
    try:
        driver.execute_script("window.stop();")
    except Exception:  # noqa: BLE001
        pass
    try:
        driver.execute_script("return document.readyState")
    except Exception:  # noqa: BLE001
        pass


def navigate(driver: webdriver.Remote, url: str, *, retries: int | None = None) -> None:
    """Open a URL with retries for Chrome/Edge renderer page-load timeouts."""
    cfg = load_selenium_config()
    attempts = int(retries if retries is not None else cfg.get("navigation_retries", 3))
    attempts = max(1, attempts)
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            driver.get(url)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not _is_renderer_timeout(exc) or attempt >= attempts:
                break
            logger.warning(
                "Navigation timeout (attempt %s/%s) for %s: %s",
                attempt,
                attempts,
                url,
                exc,
            )
            _stop_loading(driver)
            time.sleep(1.0 * attempt)
            try:
                # If the renderer died, a no-op command fails — recover via about:blank
                driver.execute_script("return 1")
            except WebDriverException:
                raise

    # Soft recovery: if DOM is usable after timeout, continue instead of failing scan
    if last_error is not None and _is_renderer_timeout(last_error):
        _stop_loading(driver)
        try:
            ready = driver.execute_script("return document.readyState")
            current = (driver.current_url or "").strip()
            if ready in {"interactive", "complete"} and current and current != "data:,":
                logger.warning(
                    "Continuing after page-load timeout; page state=%s url=%s",
                    ready,
                    current,
                )
                return
        except Exception:  # noqa: BLE001
            pass
        raise last_error
    if last_error is not None:
        raise last_error


def ensure_demo_url(url: str) -> str:
    """Start local demo server when URL points to demo port."""
    if ":8765" in url and ("127.0.0.1" in url or "localhost" in url):
        port = 8765
        try:
            port = int(url.split(":")[2].split("/")[0])
        except (IndexError, ValueError):
            pass
        return _start_demo_server(port)
    return url


def start_browser(url: str) -> webdriver.Remote:
    """Start a fresh browser session at the given URL."""
    global _driver
    if _driver is not None:
        quit_driver()
    url = ensure_demo_url(url)
    last_error: BaseException | None = None
    for attempt in range(1, 3):
        try:
            _driver = create_driver()
            navigate(_driver, url)
            return _driver
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Browser start failed (attempt %s/2): %s", attempt, exc)
            quit_driver()
            time.sleep(1.5 * attempt)
    assert last_error is not None
    raise last_error


def get_driver() -> webdriver.Remote:
    global _driver
    if _driver is None:
        _driver = create_driver()
        navigate(_driver, resolve_base_url())
    return _driver


def quit_driver(stop_server: bool = False) -> None:
    global _driver, _server
    if _driver is not None:
        try:
            _driver.quit()
        except Exception:  # noqa: BLE001
            pass
        _driver = None
    if stop_server and _server is not None:
        _server.shutdown()
        _server = None


def shutdown_all() -> None:
    quit_driver(stop_server=True)


def screenshot_on_failure(name: str) -> Path | None:
    cfg = load_selenium_config()
    if not cfg.get("screenshots_on_failure") or _driver is None:
        return None
    shot_dir = LOGS_DIR / cfg.get("screenshot_dir", "screenshots").replace("logs/", "")
    shot_dir.mkdir(parents=True, exist_ok=True)
    path = shot_dir / f"{name}.png"
    _driver.save_screenshot(str(path))
    return path
