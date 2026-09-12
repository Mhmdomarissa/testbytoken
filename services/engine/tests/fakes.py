"""Minimal Selenium-shaped fakes so runner logic can be tested without a
real browser. Implements only what the code under test actually touches —
not a general WebDriver mock."""

from __future__ import annotations

from selenium.common.exceptions import NoSuchElementException


class FakeElement:
    def __init__(
        self,
        text: str = "",
        displayed: bool = True,
        attrs: dict | None = None,
        tag_name: str = "div",
    ):
        self.text = text
        self.tag_name = tag_name
        self._displayed = displayed
        self._attrs = attrs or {}

    def is_displayed(self) -> bool:
        return self._displayed

    def get_attribute(self, name: str):
        return self._attrs.get(name)

    def clear(self) -> None:
        self.text = ""

    def send_keys(self, value: str) -> None:
        self.text = value

    def click(self) -> None:
        pass


class FakeDriver:
    """current_url / title are plain attributes, matching real WebDriver."""

    def __init__(
        self,
        current_url: str = "http://example.test/page",
        title: str = "Test Page",
        still_authenticated_redirect: tuple[str, str] | None = None,
    ):
        """still_authenticated_redirect=(login_url, dashboard_url): simulates
        an app that, while a session is still live, bounces a navigation to
        login_url straight to dashboard_url instead — the OrangeHRM-shaped
        case a logout must actually clear, not just attempt."""
        self.current_url = current_url
        self.title = title
        self._registry: dict[tuple[str, str], list[FakeElement]] = {}
        self._still_authenticated_redirect = still_authenticated_redirect

    def register(self, by: str, value: str, elements: list[FakeElement]) -> None:
        self._registry[(by, value)] = elements

    def find_element(self, by: str, value: str) -> FakeElement:
        els = self._registry.get((by, value)) or []
        if not els:
            raise NoSuchElementException(f"no element for {by}={value!r}")
        return els[0]

    def find_elements(self, by: str, value: str) -> list[FakeElement]:
        return list(self._registry.get((by, value)) or [])

    def execute_script(self, script: str, *args):
        # _execute_step's PerformClick handler polls this via WebDriverWait
        # after every click; without it, every click blocks for the full
        # real timeout (10s) waiting for a readyState that never comes.
        if "readyState" in script:
            return "complete"
        return None

    def get(self, url: str) -> None:
        if self._still_authenticated_redirect:
            login_url, dashboard_url = self._still_authenticated_redirect
            if url.split("?")[0].rstrip("/") == login_url.split("?")[0].rstrip("/"):
                self.current_url = dashboard_url
                return
        self.current_url = url

    def delete_all_cookies(self) -> None:
        pass
