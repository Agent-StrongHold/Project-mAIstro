"""Tests for maistro.auth.client — ServiceKeyClient outbound headers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from maistro.auth._types import Scope, ServiceIdentity
from maistro.auth.client import ServiceKeyClient


def _make_client() -> ServiceKeyClient:
    identity = ServiceIdentity(
        name="conductor-router",
        scopes=frozenset({Scope.CHAT_COMPLETIONS, Scope.EVENTS_EMIT}),
    )
    return ServiceKeyClient(identity=identity, key="sk-svc-conductor-test-key")


class TestServiceKeyClient:
    @pytest.mark.asyncio
    async def test_get_injects_headers(self) -> None:
        client = _make_client()
        mock_response = httpx.Response(200, request=httpx.Request("GET", "http://test"))
        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response
        ) as mock_req:
            await client.get("http://example.com/api/test")
            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
            assert headers["X-Service-Key"] == "sk-svc-conductor-test-key"
            assert headers["X-Service-Name"] == "conductor-router"

    @pytest.mark.asyncio
    async def test_post_injects_headers(self) -> None:
        client = _make_client()
        mock_response = httpx.Response(200, request=httpx.Request("POST", "http://test"))
        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response
        ) as mock_req:
            await client.post("http://example.com/api/test", json={"key": "val"})
            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
            assert headers["X-Service-Key"] == "sk-svc-conductor-test-key"

    @pytest.mark.asyncio
    async def test_custom_headers_preserved(self) -> None:
        client = _make_client()
        mock_response = httpx.Response(200, request=httpx.Request("GET", "http://test"))
        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response
        ) as mock_req:
            await client.get("http://example.com/api", headers={"X-Custom": "yes"})
            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
            assert headers["X-Custom"] == "yes"
            assert headers["X-Service-Key"] == "sk-svc-conductor-test-key"

    @pytest.mark.asyncio
    async def test_scope_header_included(self) -> None:
        client = _make_client()
        mock_response = httpx.Response(200, request=httpx.Request("GET", "http://test"))
        with patch(
            "httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_response
        ) as mock_req:
            await client.get("http://example.com/api")
            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
            scopes_header = headers.get("X-Service-Scopes", "")
            assert "llm:chat_completions" in scopes_header
            assert "events:emit" in scopes_header

    def test_identity_accessible(self) -> None:
        client = _make_client()
        assert client.identity.name == "conductor-router"
