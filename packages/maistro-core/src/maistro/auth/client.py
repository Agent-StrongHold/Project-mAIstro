"""Outbound service key client: auto-attach auth headers to HTTP requests."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from maistro.auth._types import ServiceIdentity
from maistro.http import shared_client

logger = logging.getLogger("maistro.auth.client")


class ServiceKeyClient:
    """httpx-based client that auto-injects service identity on outbound calls.

    Usage:
        client = ServiceKeyClient(
            identity=ServiceIdentity(name="conductor-router", ...),
            key="sk-svc-conductor-xxxx",
        )
        async with client.stream("POST", "http://coinswarm:8080/agents", json={...}) as resp:
            ...
    """

    def __init__(
        self,
        identity: ServiceIdentity,
        key: str,
        default_timeout: float = 15.0,
    ) -> None:
        self._identity = identity
        self._key = key
        self._default_timeout = default_timeout
        self._base_headers = {
            "X-Service-Key": key,
            "X-Service-Name": identity.name,
            "X-Service-Scopes": ",".join(s.value for s in identity.scopes),
        }

    @property
    def identity(self) -> ServiceIdentity:
        return self._identity

    def _merge_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(self._base_headers)
        if extra:
            headers.update(extra)
        return headers

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        merged = self._merge_headers(headers)
        async with shared_client(timeout=timeout or self._default_timeout) as client:
            response = await client.request(
                method,
                url,
                headers=merged,
                json=json,
                params=params,
            )
            logger.debug(
                "ServiceKeyClient %s %s %s → %d",
                self._identity.name,
                method,
                url,
                response.status_code,
            )
            return response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)
