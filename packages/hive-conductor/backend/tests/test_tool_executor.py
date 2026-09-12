"""Coverage for Hive's model-adjacent tool adapter paths.

Browser and search effects remain tool-owned; these tests only replace their
transport seams and assert that the model fallback stays an injected caller.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

import httpx
import pytest


class _Response:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers: dict[str, str] = {}
        self.is_redirect = False

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "failed",
                request=httpx.Request("GET", "https://x"),
                response=httpx.Response(self.status_code),
            )


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self._responses = iter(responses)

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def get(self, *_args: Any, **_kwargs: Any) -> _Response:
        return next(self._responses)

    async def post(self, *_args: Any, **_kwargs: Any) -> _Response:
        return next(self._responses)


async def test_search_providers_and_browser_result(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.tool_executor as tools

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(
        tools,
        "shared_client",
        lambda **_kwargs: _Client(
            [
                _Response(
                    {
                        "web": {
                            "results": [
                                {"title": "Brave", "url": "https://b", "description": "brave"}
                            ]
                        }
                    }
                ),
                _Response(
                    {"organic": [{"title": "Serper", "link": "https://s", "snippet": "serper"}]}
                ),
                _Response(
                    {
                        "answer": "Tavily summary",
                        "results": [{"title": "Tavily", "url": "https://t", "content": "tavily"}],
                    }
                ),
            ]
        ),
    )
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert (await tools.web_search("one"))["source"] == "brave"

    monkeypatch.delenv("BRAVE_SEARCH_API_KEY")
    monkeypatch.setenv("SERPER_API_KEY", "serper-key")
    assert (await tools.web_search("two"))["source"] == "serper"

    monkeypatch.delenv("SERPER_API_KEY")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    assert (await tools.web_search("three"))["source"] == "tavily"

    monkeypatch.delenv("TAVILY_API_KEY")
    from maistro.tools import browser

    class _Browser:
        async def search_web(self, query: str, *, max_results: int) -> Any:
            return SimpleNamespace(
                summary=query,
                citations=[SimpleNamespace(title="Browser", url="https://browser", snippet="hit")],
                source="browser",
            )

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(browser, "BrowserClient", _Browser)
    result = await tools.web_search("four", max_results=2)
    assert result["source"] == "browser"
    assert result["citations"][0]["title"] == "Browser"


@pytest.mark.asyncio
async def test_ssrf_redirect_and_browse_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.tool_executor as tools

    assert tools._ssrf_blocked("ftp://example.com") is not None
    assert tools._ssrf_blocked("https://") is not None

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, 0, 0, "", ("8.8.8.8", 0))],
    )
    assert tools._ssrf_blocked("https://example.com") is None
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))],
    )
    assert tools._ssrf_blocked("https://internal.example") is not None
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.gaierror()),
    )
    assert "cannot resolve" in (tools._ssrf_blocked("https://missing.example") or "")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, 0, 0, "", ("not-an-ip", 0))],
    )
    assert tools._ssrf_blocked("https://odd.example") is None
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, 0, 0, "", ("8.8.8.8", 0))],
    )

    redirect = _Response({}, text="redirect")
    redirect.is_redirect = True
    redirect.headers["location"] = "https://example.com/final"
    client = _Client([redirect, _Response({}, text="ok")])
    monkeypatch.setattr(tools, "shared_client", lambda **_kwargs: client)
    assert await tools._resolve_safe_url("https://example.com/start") == "https://example.com/final"
    redirects = []
    for _ in range(7):
        item = _Response({})
        item.is_redirect = True
        item.headers["location"] = "https://example.com/next"
        redirects.append(item)
    monkeypatch.setattr(tools, "shared_client", lambda **_kwargs: _Client(redirects))
    with pytest.raises(PermissionError, match="too many redirects"):
        await tools._resolve_safe_url("https://example.com/start")

    from maistro.tools import browser

    class _Browser:
        async def browse(self, url: str, task: str) -> Any:
            return SimpleNamespace(title="Title", text=f"{url}:{task}", duration_ms=4)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(browser, "BrowserClient", _Browser)
    monkeypatch.setattr(tools, "shared_client", lambda **_kwargs: _Client([_Response({})]))
    result = await tools.browse_url("https://example.com", "facts")
    assert result["title"] == "Title"

    class _FallbackBrowser:
        def __init__(self) -> None:
            raise RuntimeError("browser unavailable")

    monkeypatch.setattr(browser, "BrowserClient", _FallbackBrowser)
    fallback_client = _Client([_Response({}), _Response({}, text="fallback text")])
    monkeypatch.setattr(tools, "shared_client", lambda **_kwargs: fallback_client)
    result = await tools.browse_url("https://example.com")
    assert result["text"] == "fallback text"


@pytest.mark.asyncio
async def test_tool_failures_and_governed_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.tool_executor as tools

    monkeypatch.setattr(
        tools, "_resolve_safe_url", lambda _url: (_ for _ in ()).throw(PermissionError("private"))
    )
    assert "blocked" in (await tools.browse_url("https://private.example"))["error"]
    monkeypatch.setattr(
        tools, "_resolve_safe_url", lambda _url: (_ for _ in ()).throw(RuntimeError("dns"))
    )
    assert "could not resolve" in (await tools.browse_url("https://bad.example"))["error"]

    from maistro.tools import browser

    class _BrokenBrowser:
        def __init__(self) -> None:
            raise RuntimeError("browser unavailable")

    monkeypatch.setattr(browser, "BrowserClient", _BrokenBrowser)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    async def model_call(_messages: list[dict[str, Any]], **_kwargs: Any) -> str:
        return '{"summary": "model", "citations": []}'

    grounded = await tools.web_search("fallback", model_call=model_call)
    assert grounded["source"] == "gemini-grounded"

    with pytest.raises(RuntimeError, match="requires a governed"):
        await tools.clarify(["why"], {})
    with pytest.raises(RuntimeError, match="requires a governed"):
        await tools._gemini_grounded_search("bad", 1)
    with pytest.raises(RuntimeError, match="non-object"):
        await tools._gemini_grounded_search(
            "bad", 1, model_call=lambda *_args, **_kwargs: _bad_json()
        )

    async def invalid_citations(_messages: list[dict[str, Any]], **_kwargs: Any) -> str:
        return '{"summary": "bad", "citations": {}}'

    with pytest.raises(RuntimeError, match="invalid citations"):
        await tools._gemini_grounded_search("bad", 1, model_call=invalid_citations)

    async def non_object_answers(_messages: list[dict[str, Any]], **_kwargs: Any) -> str:
        return "[]"

    with pytest.raises(RuntimeError, match="non-object answers"):
        await tools.clarify(["why"], {}, model_call=non_object_answers)


async def _bad_json() -> str:
    return "[]"
