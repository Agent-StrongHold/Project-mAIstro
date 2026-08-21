"""httpx-backed AsyncHttp default — the concrete seam providers use (SPEC-187)."""

from __future__ import annotations

import httpx
import pytest

from maistro.capabilities.http import AsyncHttp
from maistro.capabilities.http_client import HttpxAsyncHttp


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_satisfies_async_http_protocol() -> None:
    client = HttpxAsyncHttp(
        "http://host:8150", transport=_mock(lambda r: httpx.Response(200, json={}))
    )
    assert isinstance(client, AsyncHttp)


async def test_get_json_hits_base_url_path_and_returns_json() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(200, json={"status": "ok"})

    client = HttpxAsyncHttp("http://host:8150", transport=_mock(handler))
    data = await client.get_json("/health")
    assert data == {"status": "ok"}
    assert seen["url"] == "http://host:8150/health"
    assert seen["method"] == "GET"


async def test_post_json_sends_body() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        seen["method"] = request.method
        return httpx.Response(200, json={"status": "started"})

    client = HttpxAsyncHttp("http://host:8150", transport=_mock(handler))
    data = await client.post_json("/action/restart_container", {"name": "litellm"})
    assert data == {"status": "started"}
    assert seen["body"] == {"name": "litellm"}
    assert seen["method"] == "POST"


async def test_bearer_token_is_attached_when_provided() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    client = HttpxAsyncHttp("http://host:8150", token="secret-tok", transport=_mock(handler))
    await client.get_json("/health")
    assert seen["auth"] == "Bearer secret-tok"


async def test_no_auth_header_without_token() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    client = HttpxAsyncHttp("http://host:8150", transport=_mock(handler))
    await client.get_json("/health")
    assert seen["auth"] is None


async def test_trailing_slash_in_base_url_does_not_double() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={})

    client = HttpxAsyncHttp("http://host:8150/", transport=_mock(handler))
    await client.get_json("/health")
    assert seen["url"] == "http://host:8150/health"


async def test_non_2xx_raises() -> None:
    client = HttpxAsyncHttp(
        "http://host:8150", transport=_mock(lambda r: httpx.Response(500, json={"e": 1}))
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_json("/full")
