"""Tests for the OpenRouter `/api/v1/activity` management-key verifier."""

from __future__ import annotations

import httpx
import pytest

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.verifiers.openrouter import (
    FREE_MODEL_RPD_WITH_CREDITS,
    OpenRouterActivityVerifier,
)


def _mock_transport(
    rows: list[dict[str, object]],
    status_code: int = 200,
    *,
    expected_key: str = "mgmt-key",
    expect_date: bool | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/activity"
        assert request.headers["authorization"] == f"Bearer {expected_key}"
        if expect_date is True:
            # verify() must scope to a single UTC day, else it sums 30 days of history.
            assert request.url.params.get("date"), "expected a ?date= day scope"
        elif expect_date is False:
            assert "date" not in request.url.params
        return httpx.Response(status_code, json={"data": rows})

    return httpx.MockTransport(handler)


async def test_fetch_activity_aggregates_and_sorts_by_requests() -> None:
    transport = _mock_transport(
        [
            {"model": "openai/gpt-oss-120b", "requests": 11, "usage": 0.0, "prompt_tokens": 100},
            {"model": "google/gemma-4-31b-it", "requests": 4, "usage": 0.0, "completion_tokens": 5},
            {"model": "openai/gpt-oss-120b", "requests": 1, "usage": 0.0, "prompt_tokens": 20},
            {"model": "qwen/qwen3-coder", "requests": 3, "usage": 0.0123, "prompt_tokens": 50},
        ]
    )
    verifier = OpenRouterActivityVerifier("mgmt-key", transport=transport)

    activity = await verifier.fetch_activity()

    # gpt-oss-120b's two rows aggregate (11 + 1 = 12) and it leads on requests.
    top = activity[0]
    assert top.model == "openai/gpt-oss-120b"
    assert top.requests == 12
    assert top.prompt_tokens == 120
    # the paid model carries its cost through.
    paid = next(u for u in activity if u.model == "qwen/qwen3-coder")
    assert paid.cost_usd == pytest.approx(0.0123)


async def test_verify_reports_free_requests_remaining() -> None:
    # 15 free requests (cost 0) used; the paid row does not count against the
    # free daily cap.
    transport = _mock_transport(
        [
            {"model": "openai/gpt-oss-120b", "requests": 12, "usage": 0.0},
            {"model": "google/gemma-4-31b-it", "requests": 3, "usage": 0.0},
            {"model": "qwen/qwen3-coder", "requests": 9, "usage": 0.5},
        ],
        expect_date=True,  # verify() scopes to today's UTC day
    )
    verifier = OpenRouterActivityVerifier("mgmt-key", transport=transport)

    snapshot = await verifier.verify()

    assert snapshot.unit == LimitUnit.REQUESTS
    assert snapshot.remaining == FREE_MODEL_RPD_WITH_CREDITS - 15
    assert snapshot.scope_key == "openrouter:free-requests"


async def test_verify_never_goes_negative() -> None:
    transport = _mock_transport([{"model": "x:free", "requests": 5000, "usage": 0.0}])
    verifier = OpenRouterActivityVerifier("mgmt-key", free_rpd_limit=1000, transport=transport)

    snapshot = await verifier.verify()

    assert snapshot.remaining == 0.0


async def test_fetch_activity_raises_on_http_error() -> None:
    transport = _mock_transport([], status_code=403)
    verifier = OpenRouterActivityVerifier("mgmt-key", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        await verifier.fetch_activity()
