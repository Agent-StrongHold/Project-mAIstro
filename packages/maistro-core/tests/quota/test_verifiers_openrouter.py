"""Tests for the OpenRouter `/api/v1/key` balance verifier."""

from __future__ import annotations

import httpx
import pytest

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.verifiers.openrouter import OpenRouterKeyVerifier


def _mock_transport(
    payload: dict[str, object], status_code: int = 200, *, expected_key: str = "test-key"
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/key"
        assert request.headers["authorization"] == f"Bearer {expected_key}"
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


async def test_verify_returns_remaining_credits() -> None:
    transport = _mock_transport(
        {"data": {"limit_remaining": 8.5, "usage": 1.5, "is_free_tier": False}}
    )
    verifier = OpenRouterKeyVerifier(api_key="test-key", transport=transport)

    snapshot = await verifier.verify("openrouter")

    assert snapshot.unit == LimitUnit.CREDITS_USD
    assert snapshot.remaining == 8.5
    assert snapshot.scope_key == "openrouter"


async def test_verify_null_limit_remaining_means_unlimited() -> None:
    transport = _mock_transport({"data": {"limit_remaining": None, "usage": 100.0}})
    verifier = OpenRouterKeyVerifier(api_key="test-key", transport=transport)

    snapshot = await verifier.verify("openrouter")

    assert snapshot.remaining == float("inf")


async def test_verify_raises_on_http_error() -> None:
    transport = _mock_transport({"error": "unauthorized"}, status_code=401, expected_key="bad-key")
    verifier = OpenRouterKeyVerifier(api_key="bad-key", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        await verifier.verify("openrouter")
