"""Tests for maistro.tools.browser.client — BrowserClient (browser-use wrapper).

The Playwright transport is the controlled double from `.fakes`: no Chromium
runtime is needed, and the guard still makes the real policy decisions. What
these tests prove about wiring is #855's core claim: the session handed to
browser-use is guarded *before* the Agent receives it, and there is no path
that runs a browser session without the guard.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

from maistro.security.outbound import reset_outbound_policy
from maistro.tools.browser.client import (
    BrowserClient,
    BrowserToolError,
    _is_truthy,
    _resolve_browser_allowed_origins,
    _resolve_browser_model,
    _resolve_llm_api_key,
    _resolve_llm_base_url,
)
from maistro.tools.browser.guard import ABORT_REASON, ROUTE_PATTERN

from .fakes import (
    FakeAsyncPlaywright,
    install_fake_playwright,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "LITELLM_URL",
        "LITELLM_BASE_URL",
        "LITELLM_PROXY_URL",
        "LITELLM_MASTER_KEY",
        "LITELLM_PROXY_KEY",
        "BROWSER_USE_MODEL",
        "BROWSER_USE_HEADLESS",
        "BROWSER_USE_TIMEOUT_S",
        "BROWSER_USE_MAX_STEPS",
        "BROWSER_USE_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_outbound_policy()


# --- fake browser-use builds ------------------------------------------------
#
# Real classes, not MagicMocks: the client inspects constructor signatures to
# decide whether a browser-use build can be handed a guarded browser, and a
# MagicMock answers `(*args, **kwargs)` — which proves nothing.


class FakeBrowserUseBrowser:
    """The 0.1-0.2 line: `Agent(browser=Browser(playwright_browser_context=...))`."""

    def __init__(self, *, playwright_browser_context: Any = None) -> None:
        self.playwright_browser_context = playwright_browser_context


class FakeBrowserUseSessionWithContext:
    """A BrowserSession build that accepts an existing context."""

    def __init__(self, *, playwright_browser_context: Any = None) -> None:
        self.playwright_browser_context = playwright_browser_context


class FakeBrowserUseSessionWithBrowser:
    """The 0.4+ line: `Agent(browser_session=BrowserSession(playwright_browser=…))`,
    where browser-use creates its own contexts from the browser it is given."""

    def __init__(self, *, playwright_browser: Any = None) -> None:
        self.playwright_browser = playwright_browser


def make_agent_cls(
    *,
    run_result: Any = None,
    run_exc: BaseException | None = None,
    navigate_urls: tuple[str, ...] = (),
) -> tuple[type, list[Any]]:
    """An Agent class recording every construction, optional behaviour on run.

    `navigate_urls` makes the fake agent drive the guarded context the way a
    real model-driven run would — including destinations the task never named
    — so the tests can watch the guard answer them.
    """
    created: list[Any] = []

    class FakeAgent:
        def __init__(
            self,
            task: str | None = None,
            llm: Any = None,
            max_steps: int | None = None,
            browser: Any = None,
            browser_session: Any = None,
        ) -> None:
            self.task = task
            self.llm = llm
            self.max_steps = max_steps
            self.browser = browser
            self.browser_session = browser_session
            created.append(self)

        async def run(self) -> Any:
            context = await self._context()
            for url in navigate_urls:
                await context.navigate(url)
            if run_exc is not None:
                raise run_exc
            return run_result

        async def _context(self) -> Any:
            if self.browser is not None:
                return self.browser.playwright_browser_context
            session = self.browser_session
            if hasattr(session, "playwright_browser_context"):
                return session.playwright_browser_context
            # The playwright_browser strategy: browser-use creates its own
            # context from the browser it was handed.
            return await session.playwright_browser.new_context()

    return FakeAgent, created


def _install_stack(
    monkeypatch: pytest.MonkeyPatch,
    agent_cls: type,
    *,
    browser_use_extra: dict[str, Any] | None = None,
) -> FakeAsyncPlaywright:
    """Fake playwright + fake browser_use module, gateway env included."""
    monkeypatch.setenv("LITELLM_URL", "http://gw")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
    pw = install_fake_playwright(monkeypatch, FakeAsyncPlaywright())
    module: dict[str, Any] = {
        "Agent": agent_cls,
        "ChatOpenAI": MagicMock(return_value="chat-instance"),
        "Browser": FakeBrowserUseBrowser,
    }
    module.update(browser_use_extra or {})
    monkeypatch.setitem(sys.modules, "browser_use", SimpleNamespace(**module))
    return pw


class TestResolveLlmBaseUrl:
    def test_uses_litellm_url_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://a/")
        monkeypatch.setenv("LITELLM_BASE_URL", "http://b")
        assert _resolve_llm_base_url() == "http://a"

    def test_falls_back_to_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_BASE_URL", "http://b/")
        assert _resolve_llm_base_url() == "http://b"

    def test_falls_back_to_proxy_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_PROXY_URL", "http://c/")
        assert _resolve_llm_base_url() == "http://c"

    def test_empty_when_unset(self) -> None:
        assert _resolve_llm_base_url() == ""


class TestResolveLlmApiKey:
    def test_uses_master_key_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_MASTER_KEY", "mk")
        monkeypatch.setenv("LITELLM_PROXY_KEY", "pk")
        assert _resolve_llm_api_key() == "mk"

    def test_falls_back_to_proxy_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_PROXY_KEY", "pk")
        assert _resolve_llm_api_key() == "pk"

    def test_empty_when_unset(self) -> None:
        assert _resolve_llm_api_key() == ""


class TestResolveBrowserModel:
    def test_default(self) -> None:
        assert _resolve_browser_model() == "gemini-3.1-flash-lite"

    def test_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_USE_MODEL", "custom-model")
        assert _resolve_browser_model() == "custom-model"


class TestResolveBrowserAllowedOrigins:
    def test_unset_yields_nothing(self) -> None:
        assert _resolve_browser_allowed_origins() == ()

    def test_comma_separated_origins_parsed_and_trimmed(self, monkeypatch) -> None:
        monkeypatch.setenv("BROWSER_USE_ALLOWED_ORIGINS", " http://a.test:9000 ,https://b.test ")
        assert _resolve_browser_allowed_origins() == ("http://a.test:9000", "https://b.test")


class TestIsTruthy:
    @pytest.mark.parametrize("val", ["1", "true", "True", "yes", "on"])
    def test_truthy_values(self, val: str) -> None:
        assert _is_truthy(val) is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "", None])
    def test_falsy_values(self, val: str | None) -> None:
        assert _is_truthy(val) is False


class TestInit:
    def test_defaults(self) -> None:
        client = BrowserClient()
        assert client.llm_model == "gemini-3.1-flash-lite"
        assert client.headless is True
        assert client.timeout_s == 90.0
        assert client.max_steps == 15

    def test_explicit_overrides(self) -> None:
        client = BrowserClient(llm_model="m", headless=False, timeout_s=30, max_steps=5)
        assert client.llm_model == "m"
        assert client.headless is False
        assert client.timeout_s == 30.0
        assert client.max_steps == 5

    def test_headless_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_USE_HEADLESS", "false")
        client = BrowserClient()
        assert client.headless is False

    def test_timeout_and_max_steps_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_USE_TIMEOUT_S", "45")
        monkeypatch.setenv("BROWSER_USE_MAX_STEPS", "7")
        client = BrowserClient()
        assert client.timeout_s == 45.0
        assert client.max_steps == 7

    def test_no_net_events_before_any_run(self) -> None:
        assert BrowserClient().last_net_events() == ()


class TestImportBrowserUse:
    def test_raises_browser_tool_error_when_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "browser_use", None)
        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="browser-use not installed"):
            client._import_browser_use()

    def test_caches_after_first_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_module = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)
        client = BrowserClient()
        first = client._import_browser_use()
        second = client._import_browser_use()
        assert first is fake_module
        assert second is fake_module


class TestBuildLlm:
    def test_raises_when_gateway_not_configured(self) -> None:
        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="LLM gateway not configured"):
            client._build_llm()

    def test_uses_chat_openai_top_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(ChatOpenAI=fake_chat_openai_cls)
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)
        client = BrowserClient(llm_model="m")
        result = client._build_llm()
        assert result == "chat-instance"
        fake_chat_openai_cls.assert_called_once_with(
            model="m", base_url="http://gw", api_key="key", temperature=0.1
        )

    def test_uses_chat_openai_nested_under_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(llm=SimpleNamespace(ChatOpenAI=fake_chat_openai_cls))
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)
        client = BrowserClient()
        result = client._build_llm()
        assert result == "chat-instance"

    def test_falls_back_to_async_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        fake_module = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)
        fake_async_openai_cls = MagicMock(return_value="async-openai-instance")
        fake_openai_module = SimpleNamespace(AsyncOpenAI=fake_async_openai_cls)
        monkeypatch.setitem(sys.modules, "openai", fake_openai_module)
        client = BrowserClient()
        result = client._build_llm()
        assert result == "async-openai-instance"
        fake_async_openai_cls.assert_called_once_with(base_url="http://gw", api_key="key")


class TestSearchWeb:
    @pytest.mark.asyncio
    async def test_raises_when_agent_class_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_module = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)
        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="Agent class not available"):
            await client.search_web("test query")

    @pytest.mark.asyncio
    async def test_success_returns_search_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent_cls, _created = make_agent_cls(
            run_result=SimpleNamespace(final_result='{"summary": "the summary", "citations": []}')
        )
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        result = await client.search_web("test query", max_results=2)

        assert result.query == "test query"
        assert result.summary == "the summary"
        assert result.source == "browser-use"

    @pytest.mark.asyncio
    async def test_timeout_raises_browser_tool_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent_cls, _created = make_agent_cls(run_exc=TimeoutError())
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="timed out"):
            await client.search_web("test query")

    @pytest.mark.asyncio
    async def test_generic_exception_wraps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent_cls, _created = make_agent_cls(run_exc=ValueError("boom"))
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="search_web failed"):
            await client.search_web("test query")


class TestBrowseSSRFGuard:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/admin",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    async def test_blocked_url_rejected_before_agent_constructed(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        agent_cls, created = make_agent_cls()
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="SSRF guard"):
            await client.browse(url, "find something")

        assert created == []


class TestBrowse:
    @pytest.mark.asyncio
    async def test_raises_when_agent_class_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_module = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)
        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="Agent class not available"):
            await client.browse("https://example.com", "find something")

    @pytest.mark.asyncio
    async def test_success_returns_browse_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent_cls, _created = make_agent_cls(
            run_result=SimpleNamespace(final_result="some text", title="Page Title")
        )
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        result = await client.browse("https://example.com", "find something")

        assert result.url == "https://example.com"
        assert result.title == "Page Title"
        assert result.text == "some text"

    @pytest.mark.asyncio
    async def test_title_falls_back_to_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent_cls, _created = make_agent_cls(run_result=SimpleNamespace(final_result="some text"))
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        result = await client.browse("https://example.com", "find something")
        assert result.title == "https://example.com"

    @pytest.mark.asyncio
    async def test_exception_wraps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent_cls, _created = make_agent_cls(run_exc=ValueError("boom"))
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="browse failed"):
            await client.browse("https://example.com", "find something")


# --- the governed session (#855) --------------------------------------------


class TestGuardedSession:
    @pytest.mark.asyncio
    async def test_search_web_attaches_the_guard_before_the_agent_sees_the_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_cls, created = make_agent_cls(
            run_result=SimpleNamespace(final_result='{"summary": "s", "citations": []}')
        )
        pw = _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        await client.search_web("test query")

        agent = created[0]
        context = agent.browser.playwright_browser_context
        # The catch-all route was registered on the very context the Agent ran on.
        assert [p for p, _h in context.route_handlers] == [ROUTE_PATTERN]
        # And that context is the one this client launched.
        assert pw.chromium.browsers[0].contexts == [context]
        assert pw.chromium.launch_kwargs == [{"headless": True}]
        assert context.init_kwargs.get("service_workers") == "block"

    @pytest.mark.asyncio
    async def test_browse_runs_on_a_guarded_session_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_cls, created = make_agent_cls(run_result=SimpleNamespace(final_result="text"))
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        await client.browse("https://example.com", "summarize")

        context = created[0].browser.playwright_browser_context
        assert [p for p, _h in context.route_handlers] == [ROUTE_PATTERN]

    @pytest.mark.asyncio
    async def test_the_playwright_objects_are_torn_down_after_a_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_cls, created = make_agent_cls(run_result=SimpleNamespace(final_result="text"))
        pw = _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        await client.browse("https://example.com", "summarize")

        context = created[0].browser.playwright_browser_context
        assert context.closed is True
        assert pw.chromium.browsers[0].closed is True
        assert pw.stopped is True

    @pytest.mark.asyncio
    async def test_a_failed_run_still_tears_the_browser_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_cls, created = make_agent_cls(run_exc=ValueError("boom"))
        pw = _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="browse failed"):
            await client.browse("https://example.com", "summarize")

        context = created[0].browser.playwright_browser_context
        assert context.closed is True
        assert pw.chromium.browsers[0].closed is True

    @pytest.mark.asyncio
    async def test_playwright_missing_is_a_refusal_not_an_unguarded_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_cls, _created = make_agent_cls(run_result=SimpleNamespace(final_result="text"))
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        monkeypatch.setitem(
            sys.modules,
            "browser_use",
            SimpleNamespace(
                Agent=agent_cls,
                ChatOpenAI=MagicMock(return_value="chat-instance"),
                Browser=FakeBrowserUseBrowser,
            ),
        )
        # `sys.modules[name] = None` makes the import raise ImportError.
        monkeypatch.setitem(sys.modules, "playwright", None)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="playwright not installed"):
            await client.browse("https://example.com", "summarize")


class TestGuardedSessionBrowserUseStrategies:
    """browser-use has changed how an external browser is handed over; each
    supported shape must end up governed, and an unmatchable build must be
    refused rather than run unguarded."""

    @pytest.mark.asyncio
    async def test_browser_session_accepting_a_context_is_governed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _agent_cls, created = make_agent_cls(run_result=SimpleNamespace(final_result="text"))

        class _ContextAgent:
            def __init__(
                self,
                task: str | None = None,
                llm: Any = None,
                max_steps: int | None = None,
                browser_session: Any = None,
            ) -> None:
                self.browser_session = browser_session
                created.append(self)

            async def run(self) -> Any:
                return SimpleNamespace(final_result="text")

        pw = _install_stack(
            monkeypatch,
            _ContextAgent,
            browser_use_extra={
                "Browser": None,  # this build has no Browser class
                "BrowserSession": FakeBrowserUseSessionWithContext,
            },
        )

        client = BrowserClient()
        await client.search_web("q")

        context = created[0].browser_session.playwright_browser_context
        assert context is pw.chromium.browsers[0].contexts[0]
        assert [p for p, _h in context.route_handlers] == [ROUTE_PATTERN]

    @pytest.mark.asyncio
    async def test_browser_session_creating_its_own_context_is_governed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 0.4+ shape: browser-use makes its context from the browser it
        was handed. The wrapper must guard that context at creation."""

        class _SessionAgent:
            created: ClassVar[list[Any]] = []

            def __init__(
                self,
                task: str | None = None,
                llm: Any = None,
                max_steps: int | None = None,
                browser_session: Any = None,
            ) -> None:
                self.browser_session = browser_session
                _SessionAgent.created.append(self)

            async def run(self) -> Any:
                context = await self.browser_session.playwright_browser.new_context()
                route = await context.navigate("http://127.0.0.1:9999/admin")
                assert route.action == ("abort", ABORT_REASON)
                return SimpleNamespace(final_result="text")

        _install_stack(
            monkeypatch,
            _SessionAgent,
            browser_use_extra={
                "Browser": None,
                "BrowserSession": FakeBrowserUseSessionWithBrowser,
            },
        )

        client = BrowserClient()
        result = await client.search_web("q")
        assert result.summary == "text"
        assert client.last_net_events(), "the guarded context's decisions must be auditable"

    @pytest.mark.asyncio
    async def test_an_ungovernable_browser_use_build_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _BareAgent:
            def __init__(
                self, task: str | None = None, llm: Any = None, max_steps: int | None = None
            ) -> None:
                pass

            async def run(self) -> Any:
                raise AssertionError("must not run: the session was ungoverned")

        pw = _install_stack(
            monkeypatch,
            _BareAgent,
            browser_use_extra={"Browser": None},
        )

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="cannot be governed"):
            await client.search_web("q")

        # Refused, and nothing was left running.
        assert pw.chromium.browsers[0].contexts[0].closed is True
        assert pw.chromium.browsers[0].closed is True
        assert pw.stopped is True

    @pytest.mark.asyncio
    async def test_a_swallowing_ctor_does_not_count_as_governed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`**kwargs` proves nothing: a build that would silently ignore the
        browser we hand it and build its own is not governable."""

        class _SwallowingSession:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs

        class _SwallowAgent:
            def __init__(
                self,
                task: str | None = None,
                llm: Any = None,
                max_steps: int | None = None,
                browser_session: Any = None,
            ) -> None:
                pass

            async def run(self) -> Any:
                raise AssertionError("must not run")

        _install_stack(
            monkeypatch,
            _SwallowAgent,
            browser_use_extra={"Browser": None, "BrowserSession": _SwallowingSession},
        )

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="cannot be governed"):
            await client.search_web("q")


class TestModelDirectedNavigation:
    """#855/AC-3: the autonomous agent's own destinations are governed."""

    @pytest.mark.asyncio
    async def test_search_web_denies_a_destination_the_model_invented(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_cls, _created = make_agent_cls(
            run_result=SimpleNamespace(final_result='{"summary": "s", "citations": []}'),
            navigate_urls=("https://example.com/", "http://127.0.0.1:9999/admin"),
        )
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        result = await client.search_web("test query")

        # The run completes — a denial is a navigation failure, not a crash —
        # and the evidence of both decisions is on the client.
        assert result.source == "browser-use"
        events = client.last_net_events()
        assert [e.decision for e in events] == ["allowed", "denied"]
        assert events[-1].origin == "http://127.0.0.1:9999"

    @pytest.mark.asyncio
    async def test_browse_denies_a_redirect_hop_into_a_private_target(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_cls, _created = make_agent_cls(
            run_result=SimpleNamespace(final_result="text"),
            navigate_urls=(
                "https://example.com/start",
                "http://169.254.169.254/latest/meta-data/",
            ),
        )
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        await client.browse("https://example.com/start", "summarize")

        events = client.last_net_events()
        assert [e.decision for e in events] == ["allowed", "denied"]
        assert events[-1].origin == "http://169.254.169.254:80"

    @pytest.mark.asyncio
    async def test_host_configured_browser_origins_are_reachable_and_scoped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BROWSER_USE_ALLOWED_ORIGINS", "http://internal.example:9000")
        agent_cls, _created = make_agent_cls(
            run_result=SimpleNamespace(final_result="text"),
            navigate_urls=(
                "http://internal.example:9000/wiki",  # the allowed exception
                "http://internal.example:9001/wiki",  # same host, other port
            ),
        )
        _install_stack(monkeypatch, agent_cls)

        client = BrowserClient()
        await client.browse("https://example.com/start", "summarize")

        events = client.last_net_events()
        assert [e.decision for e in events] == ["allowed", "denied"]


class TestAclose:
    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        client = BrowserClient()
        assert await client.aclose() is None


class TestParseSearchOutput:
    def test_parses_json_summary_and_citations(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(
            final_result='{"summary": "s", "citations": [{"title": "t", "url": "u", "snippet": "sn"}]}'
        )
        result = client._parse_search_output("q", run_result, 100)
        assert result.summary == "s"
        assert len(result.citations) == 1
        assert result.citations[0].title == "t"

    def test_parses_sources_key_as_citations_alias(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(
            final_result='{"summary": "s", "sources": [{"title": "t", "url": "u"}]}'
        )
        result = client._parse_search_output("q", run_result, 100)
        assert len(result.citations) == 1

    def test_strips_markdown_json_fences(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(final_result='```json\n{"summary": "fenced"}\n```')
        result = client._parse_search_output("q", run_result, 100)
        assert result.summary == "fenced"

    def test_non_dict_json_falls_back_to_raw_text(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(final_result="[1, 2, 3]")
        result = client._parse_search_output("q", run_result, 100)
        assert result.summary == "[1, 2, 3]"

    def test_invalid_json_falls_back_to_raw_text(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(final_result="not json at all")
        result = client._parse_search_output("q", run_result, 100)
        assert result.summary == "not json at all"

    def test_empty_text_falls_back_to_no_content_message(self) -> None:
        client = BrowserClient()
        result = client._parse_search_output("my query", None, 100)
        assert "No content returned for query: my query" in result.summary

    def test_citations_skip_entries_missing_url(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(
            final_result='{"summary": "s", "citations": [{"title": "no-url"}, {"title": "t", "url": "u"}]}'
        )
        result = client._parse_search_output("q", run_result, 100)
        assert len(result.citations) == 1
        assert result.citations[0].url == "u"

    def test_raw_citations_not_a_list_ignored(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(final_result='{"summary": "s", "citations": "not-a-list"}')
        result = client._parse_search_output("q", run_result, 100)
        assert result.citations == ()

    def test_long_text_summary_truncated_to_600_chars(self) -> None:
        client = BrowserClient()
        long_text = "x" * 1000
        run_result = SimpleNamespace(final_result=long_text)
        result = client._parse_search_output("q", run_result, 100)
        assert len(result.summary) == 600

    def test_source_marked_duckduckgo_fallback(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(final_result='{"summary": "found via duckduckgo results"}')
        result = client._parse_search_output("q", run_result, 100)
        assert result.source == "duckduckgo-fallback"

    def test_source_marked_error_when_unreachable(self) -> None:
        client = BrowserClient()
        run_result = SimpleNamespace(final_result='{"summary": "search engines unreachable"}')
        result = client._parse_search_output("q", run_result, 100)
        assert result.source == "error"


class TestExtractText:
    @pytest.mark.parametrize("attr", ["final_result", "output", "last_message", "result"])
    def test_extracts_first_present_attr(self, attr: str) -> None:
        run_result = SimpleNamespace(**{attr: "value"})
        assert BrowserClient._extract_text(run_result) == "value"

    def test_falls_back_to_str_of_run_result(self) -> None:
        assert BrowserClient._extract_text("plain string") == "plain string"

    def test_none_run_result_returns_empty_string(self) -> None:
        assert BrowserClient._extract_text(None) == ""


class TestExtractTitle:
    def test_extracts_title_attr(self) -> None:
        run_result = SimpleNamespace(title="My Title")
        assert BrowserClient._extract_title(run_result) == "My Title"

    def test_returns_none_when_missing(self) -> None:
        run_result = SimpleNamespace()
        assert BrowserClient._extract_title(run_result) is None
