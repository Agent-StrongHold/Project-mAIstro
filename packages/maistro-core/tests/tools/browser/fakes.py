"""A controlled Playwright/browser transport for the browser tests (#855).

The dev environment does not install Playwright or Chromium — the browser
surface is optional and baked into the research image — and the tests must
not need the network beyond DNS. What they need is the *shape* of the
transport: a context whose requests pass through registered route handlers
before any socket would be opened. These doubles provide exactly that, so a
test can `await context.navigate(url)` and observe the decision the guard
made — continue, or abort — the same way Chromium would deliver it.

Nothing here fabricates policy outcomes; the guard runs for real and makes
the real decision. Only the wire is fake.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any


class FakePwRequest:
    """Playwright's `Request`: what the route handler is asked about."""

    def __init__(self, url: str, resource_type: str = "document") -> None:
        self.url = url
        self.resource_type = resource_type


class FakePwRoute:
    """Playwright's `Route`: how a handler answers a request.

    `action` records the answer so a test can assert on it: `("continue",)`
    or `("abort", code)`. If a handler answers twice, the second call
    raises, like Playwright does.
    """

    def __init__(self, request: FakePwRequest) -> None:
        self.request = request
        self.action: tuple[str, ...] | None = None

    async def continue_(self, **kwargs: Any) -> None:
        if self.action is not None:
            raise RuntimeError("route already handled")
        self.action = ("continue",)

    async def abort(self, error_code: str = "failed") -> None:
        if self.action is not None:
            raise RuntimeError("route already handled")
        self.action = ("abort", error_code)


class FakePwWebSocketRoute:
    """Playwright's `WebSocketRoute` (the `route_web_socket` handler's arg)."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.action: tuple[str, ...] | None = None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.action = ("close", code)


class FakePwContext:
    """A Playwright `BrowserContext` driven by hand.

    `navigate` / `open_web_socket` push a request through every registered
    handler — the point in real Chromium where the network stack is about
    to connect, and where the guard's decision applies.
    """

    def __init__(self) -> None:
        self.route_handlers: list[tuple[str, Any]] = []
        self.ws_handlers: list[tuple[str, Any]] = []
        self.closed = False
        #: Whether service workers were blocked at creation.
        self.init_kwargs: dict[str, Any] = {}

    async def route(self, pattern: str, handler: Any) -> None:
        self.route_handlers.append((pattern, handler))

    async def route_web_socket(self, pattern: str, handler: Any) -> None:
        self.ws_handlers.append((pattern, handler))

    async def navigate(self, url: str, resource_type: str = "document") -> FakePwRoute:
        request = FakePwRequest(url, resource_type)
        route = FakePwRoute(request)
        for _pattern, handler in self.route_handlers:
            await handler(route, request)
        return route

    async def open_web_socket(self, url: str) -> FakePwWebSocketRoute:
        ws = FakePwWebSocketRoute(url)
        for _pattern, handler in self.ws_handlers:
            await handler(ws)
        return ws

    async def close(self) -> None:
        self.closed = True


class FakePwBrowser:
    """A Playwright `Browser` handing out `FakePwContext`s."""

    def __init__(self) -> None:
        self.contexts: list[FakePwContext] = []
        self.closed = False

    async def new_context(self, **kwargs: Any) -> FakePwContext:
        context = FakePwContext()
        context.init_kwargs = dict(kwargs)
        self.contexts.append(context)
        return context

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self) -> None:
        self.launch_kwargs: list[dict[str, Any]] = []
        self.browsers: list[FakePwBrowser] = []

    async def launch(self, **kwargs: Any) -> FakePwBrowser:
        self.launch_kwargs.append(dict(kwargs))
        browser = FakePwBrowser()
        self.browsers.append(browser)
        return browser


class FakeAsyncPlaywright:
    """The object `async_playwright().start()` returns."""

    def __init__(self) -> None:
        self.chromium = FakeChromium()
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _PlaywrightStarter:
    def __init__(self, pw: FakeAsyncPlaywright) -> None:
        self._pw = pw
        self.started = False

    async def start(self) -> FakeAsyncPlaywright:
        self.started = True
        return self._pw


def fake_async_playwright_factory(pw: FakeAsyncPlaywright) -> Any:
    """A callable standing in for `playwright.async_api.async_playwright`."""

    def _async_playwright() -> _PlaywrightStarter:
        return _PlaywrightStarter(pw)

    return _async_playwright


def install_fake_playwright(monkeypatch: Any, pw: FakeAsyncPlaywright) -> FakeAsyncPlaywright:
    """Put `playwright.async_api.async_playwright` into sys.modules as `pw`.

    Both `playwright` and `playwright.async_api` are registered: the client
    imports `from playwright.async_api import async_playwright`, and the
    import machinery resolves the submodule from sys.modules only when the
    parent advertises it — a bare namespace without a module entry cannot
    serve that import.
    """
    import sys

    async_api = ModuleType("playwright.async_api")
    async_api.async_playwright = fake_async_playwright_factory(pw)  # type: ignore[attr-defined]
    top = ModuleType("playwright")
    top.async_api = async_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", top)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)
    return pw
