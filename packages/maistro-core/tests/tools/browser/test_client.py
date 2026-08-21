"""Tests for maistro.tools.browser.client — BrowserClient (browser-use wrapper)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from maistro.tools.browser.client import (
    BrowserClient,
    BrowserToolError,
    _is_truthy,
    _resolve_browser_model,
    _resolve_llm_api_key,
    _resolve_llm_base_url,
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
    ):
        monkeypatch.delenv(var, raising=False)


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
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        run_result = SimpleNamespace(final_result='{"summary": "the summary", "citations": []}')
        fake_agent_instance = SimpleNamespace(run=AsyncMock(return_value=run_result))
        fake_agent_cls = MagicMock(return_value=fake_agent_instance)
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(Agent=fake_agent_cls, ChatOpenAI=fake_chat_openai_cls)
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)

        client = BrowserClient()
        result = await client.search_web("test query", max_results=2)

        assert result.query == "test query"
        assert result.summary == "the summary"
        assert result.source == "browser-use"

    @pytest.mark.asyncio
    async def test_timeout_raises_browser_tool_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        fake_agent_instance = SimpleNamespace(run=AsyncMock(side_effect=TimeoutError))
        fake_agent_cls = MagicMock(return_value=fake_agent_instance)
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(Agent=fake_agent_cls, ChatOpenAI=fake_chat_openai_cls)
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="timed out"):
            await client.search_web("test query")

    @pytest.mark.asyncio
    async def test_generic_exception_wraps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        fake_agent_instance = SimpleNamespace(run=AsyncMock(side_effect=ValueError("boom")))
        fake_agent_cls = MagicMock(return_value=fake_agent_instance)
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(Agent=fake_agent_cls, ChatOpenAI=fake_chat_openai_cls)
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)

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
        fake_agent_cls = MagicMock()
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(Agent=fake_agent_cls, ChatOpenAI=fake_chat_openai_cls)
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="SSRF guard"):
            await client.browse(url, "find something")

        fake_agent_cls.assert_not_called()


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
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        run_result = SimpleNamespace(final_result="some text", title="Page Title")
        fake_agent_instance = SimpleNamespace(run=AsyncMock(return_value=run_result))
        fake_agent_cls = MagicMock(return_value=fake_agent_instance)
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(Agent=fake_agent_cls, ChatOpenAI=fake_chat_openai_cls)
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)

        client = BrowserClient()
        result = await client.browse("https://example.com", "find something")

        assert result.url == "https://example.com"
        assert result.title == "Page Title"
        assert result.text == "some text"

    @pytest.mark.asyncio
    async def test_title_falls_back_to_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        run_result = SimpleNamespace(final_result="some text")
        fake_agent_instance = SimpleNamespace(run=AsyncMock(return_value=run_result))
        fake_agent_cls = MagicMock(return_value=fake_agent_instance)
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(Agent=fake_agent_cls, ChatOpenAI=fake_chat_openai_cls)
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)

        client = BrowserClient()
        result = await client.browse("https://example.com", "find something")
        assert result.title == "https://example.com"

    @pytest.mark.asyncio
    async def test_exception_wraps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_URL", "http://gw")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "key")
        fake_agent_instance = SimpleNamespace(run=AsyncMock(side_effect=ValueError("boom")))
        fake_agent_cls = MagicMock(return_value=fake_agent_instance)
        fake_chat_openai_cls = MagicMock(return_value="chat-instance")
        fake_module = SimpleNamespace(Agent=fake_agent_cls, ChatOpenAI=fake_chat_openai_cls)
        monkeypatch.setitem(sys.modules, "browser_use", fake_module)

        client = BrowserClient()
        with pytest.raises(BrowserToolError, match="browse failed"):
            await client.browse("https://example.com", "find something")


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
