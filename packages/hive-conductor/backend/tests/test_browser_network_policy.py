"""The Conductor's direct Playwright callers use the canonical browser seam."""

from __future__ import annotations

import sys
import types
from typing import Any


class _Request:
    def __init__(self, url: str) -> None:
        self.url = url
        self.resource_type = "document"


class _Response:
    status = 200
    headers: dict[str, str]

    def __init__(self) -> None:
        self.headers = {}


class _Route:
    def __init__(self, request: _Request) -> None:
        self.request = request
        self.action: tuple[str, ...] | None = None
        self.fetch_count = 0

    async def fetch(self, **_kwargs: Any) -> _Response:
        self.fetch_count += 1
        return _Response()

    async def fulfill(self, *, response: _Response) -> None:
        self.action = ("fulfill",)

    async def abort(self, reason: str) -> None:
        self.action = ("abort", reason)


class _Page:
    def __init__(self, context: _Context) -> None:
        self.context = context
        self.last_route: _Route | None = None

    async def goto(self, url: str, **_kwargs: Any) -> None:
        request = _Request(url)
        route = _Route(request)
        self.last_route = route
        for _pattern, handler in self.context.routes:
            await handler(route, request)
        if route.action and route.action[0] == "abort":
            raise RuntimeError("navigation blocked")

    async def wait_for_timeout(self, _timeout_ms: int) -> None:
        pass

    async def screenshot(self, **_kwargs: Any) -> bytes:
        return b"png"

    def locator(self, _selector: str) -> _Locator:
        return _Locator()


class _Locator:
    async def is_visible(self, **_kwargs: Any) -> bool:
        return False

    async def click(self) -> None:
        pass


class _Context:
    def __init__(self) -> None:
        self.routes: list[tuple[str, Any]] = []
        self.service_workers: str | None = None
        self.page = _Page(self)
        self.closed = False

    async def route(self, pattern: str, handler: Any) -> None:
        self.routes.append((pattern, handler))

    async def route_web_socket(self, _pattern: str, _handler: Any) -> None:
        pass

    async def add_cookies(self, _cookies: list[dict[str, str]]) -> None:
        pass

    async def new_page(self) -> _Page:
        return self.page

    async def close(self) -> None:
        self.closed = True


class _Browser:
    def __init__(self) -> None:
        self.context: _Context | None = None
        self.closed = False

    async def new_context(self, **kwargs: Any) -> _Context:
        self.context = _Context()
        self.context.service_workers = kwargs.get("service_workers")
        return self.context

    async def close(self) -> None:
        self.closed = True


class _Playwright:
    def __init__(self) -> None:
        self.chromium = self
        self.browser: _Browser | None = None
        self.stopped = False

    async def launch(self, **_kwargs: Any) -> _Browser:
        self.browser = _Browser()
        return self.browser

    async def stop(self) -> None:
        self.stopped = True


class _Starter:
    def __init__(self, playwright: _Playwright) -> None:
        self.playwright = playwright

    async def start(self) -> _Playwright:
        return self.playwright

    async def __aenter__(self) -> _Playwright:
        return self.playwright

    async def __aexit__(self, *_args: Any) -> None:
        await self.playwright.stop()


def _install_playwright(monkeypatch: Any) -> _Playwright:
    playwright = _Playwright()
    api = types.ModuleType("playwright.async_api")
    api.async_playwright = lambda: _Starter(playwright)  # type: ignore[attr-defined]
    package = types.ModuleType("playwright")
    package.async_api = api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.async_api", api)
    return playwright


async def test_dashboard_screenshot_attaches_guard_before_fixed_internal_navigation(
    monkeypatch: Any,
) -> None:
    from routes import widgets

    playwright = _install_playwright(monkeypatch)
    result = await widgets.capture_screenshot(type("Request", (), {"cookies": {}})())

    assert result["screenshot"]
    assert playwright.browser is not None and playwright.browser.context is not None
    context = playwright.browser.context
    assert context.service_workers == "block"
    assert context.page.last_route is not None
    assert context.page.last_route.action == ("fulfill",)
    assert context.page.last_route.fetch_count == 1


async def test_hill_climber_screenshot_blocks_model_or_cli_loopback_navigation(
    monkeypatch: Any,
) -> None:
    from services import ui_auto_climb

    playwright = _install_playwright(monkeypatch)
    result = await ui_auto_climb.screenshot("http://127.0.0.1:9", "/model-directed")

    assert result == ""
    assert playwright.browser is not None and playwright.browser.context is not None
    route = playwright.browser.context.page.last_route
    assert route is not None
    assert route.action == ("abort", "blockedbyclient")
    assert route.fetch_count == 0


def test_hyperlight_hill_climb_guards_each_sync_browser_context() -> None:
    """Keep the reachable VM workload on the same browser transport seam."""
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "hill-climb-ui.sh"
    source = script.read_text()

    assert "configure_outbound_policy(BASE, URL)" in source
    assert "with sync_client(timeout=60.0) as client:" in source
    assert "httpx.post(" not in source
    assert 'service_workers="block"' in source
    assert (
        "SyncBrowserNetworkGuard(extra_origins=browser_allowed_origins()).attach(context)" in source
    )
    assert source.count("ctx = guarded_context(browser)") == 2
    assert "browser.new_page(" not in source
