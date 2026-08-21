"""Concrete httpx-backed `AsyncHttp` — the default seam for HTTP-backed providers.

Providers (e.g. the host-health monitor/action) depend on the `AsyncHttp`
protocol; this is the production implementation. The app constructs one pointed
at the service base URL with a bearer token, then injects it into the providers.
A `transport` is injectable so tests exercise the real client + header logic
against an `httpx.MockTransport` without a network.
"""

from __future__ import annotations

from typing import Any

import httpx

from maistro.http import get_shared_client

_DEFAULT_TIMEOUT = 10.0


class HttpxAsyncHttp:
    """AsyncHttp backed by the shared, pooled client for its configuration.

    This used to open a fresh client per request, for a good reason: an
    `AsyncClient` binds to the event loop that created it, so a client held on
    long-lived app state breaks when a second loop touches it. `maistro.http`
    keeps that property — its cache is keyed by the running loop — while
    removing the per-request construction cost and giving connection reuse.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._headers: dict[str, str] = {}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def _client(self) -> httpx.AsyncClient:
        return get_shared_client(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._timeout,
            transport=self._transport,
        )

    async def get_json(self, path: str) -> dict[str, Any]:
        resp = await self._client().get(path)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    async def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client().post(path, json=body)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data
