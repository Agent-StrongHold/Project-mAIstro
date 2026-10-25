"""Tests for the Mistral Admin API rate-limit verifier.

The endpoint's exact response schema is not publicly documented (see the
module docstring on `quota/verifiers/mistral.py`) -- these tests cover the
defensive field-extraction behavior against several plausible shapes, plus
the "none of the candidates matched" failure path.
"""

from __future__ import annotations

import httpx
import pytest

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.verifiers.mistral import MistralAdminApiVerifier


def _mock_transport(
    payload: dict[str, object], status_code: int = 200, *, expected_key: str = "admin-key"
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/admin/rate-limit"
        assert request.headers["x-api-key"] == expected_key
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


async def test_verify_uses_x_api_key_header_not_bearer() -> None:
    transport = _mock_transport({"remaining": 42})
    verifier = MistralAdminApiVerifier(admin_api_key="admin-key", transport=transport)

    snapshot = await verifier.verify("mistral:mistral-small")

    assert snapshot.remaining == 42.0
    assert snapshot.unit == LimitUnit.REQUESTS
    assert snapshot.scope_key == "mistral:mistral-small"


@pytest.mark.parametrize(
    "field",
    ["remaining", "requests_remaining", "rate_limit_remaining", "remaining_requests"],
)
async def test_verify_accepts_each_candidate_field_name(field: str) -> None:
    transport = _mock_transport({field: 7})
    verifier = MistralAdminApiVerifier(admin_api_key="admin-key", transport=transport)

    snapshot = await verifier.verify("mistral:mistral-small")

    assert snapshot.remaining == 7.0


async def test_verify_raises_when_no_candidate_field_present() -> None:
    transport = _mock_transport({"some_other_field": 1})
    verifier = MistralAdminApiVerifier(admin_api_key="admin-key", transport=transport)

    with pytest.raises(RuntimeError, match="did not contain a recognized"):
        await verifier.verify("mistral:mistral-small")


async def test_verify_raises_on_http_error() -> None:
    transport = _mock_transport({"error": "unauthorized"}, status_code=401, expected_key="bad-key")
    verifier = MistralAdminApiVerifier(admin_api_key="bad-key", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        await verifier.verify("mistral:mistral-small")


async def test_first_matching_candidate_field_wins() -> None:
    transport = _mock_transport({"remaining": 5, "requests_remaining": 999})
    verifier = MistralAdminApiVerifier(admin_api_key="admin-key", transport=transport)

    snapshot = await verifier.verify("mistral:mistral-small")

    assert snapshot.remaining == 5.0
