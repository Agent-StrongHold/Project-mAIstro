"""Tests for the Mistral Admin API rate-limit verifier.

The endpoint's response schema is not publicly documented and is NOT confirmed
(#1205): the verifier therefore refuses to guess. These tests pin the explicit
`MistralRateLimitSchema` contract — one named field, strict type/range
validation, and failure (never fallback) on any deviation from the declared
shape.
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.verifiers.mistral import (
    MistralAdminApiVerifier,
    MistralRateLimitSchema,
    MistralSchemaContractError,
    _extract_remaining,
)

SCHEMA = MistralRateLimitSchema(version="confirmed-2026-field-study", remaining_field="remaining")


def _mock_transport(
    payload: object, status_code: int = 200, *, expected_key: str = "admin-key"
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/admin/rate-limit"
        assert request.headers["x-api-key"] == expected_key
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


def _verifier(transport: httpx.MockTransport) -> MistralAdminApiVerifier:
    return MistralAdminApiVerifier(admin_api_key="admin-key", schema=SCHEMA, transport=transport)


def test_schema_contract_is_required_not_guessed() -> None:
    """#1205: no construction without an explicit schema — the guessing
    revision's zero-argument contract must stay impossible."""
    params = inspect.signature(MistralAdminApiVerifier.__init__).parameters
    assert "schema" in params
    assert params["schema"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["schema"].default is inspect.Parameter.empty


async def test_verify_uses_x_api_key_header_not_bearer() -> None:
    transport = _mock_transport({"remaining": 42})
    verifier = _verifier(transport)

    snapshot = await verifier.verify("mistral:mistral-small")

    assert snapshot.remaining == 42.0
    assert snapshot.unit == LimitUnit.REQUESTS
    assert snapshot.scope_key == "mistral:mistral-small"


async def test_verify_parses_only_the_contract_declared_field() -> None:
    """#1205: a plausible-looking *other* remaining field must not be adopted
    — first-match-wins over a guess list is the exact failure this verifier
    retired. The declared contract names `remaining`; `requests_remaining` in
    the payload is ignored, and its absence would be an error, not a fallback."""
    transport = _mock_transport({"remaining": 7, "requests_remaining": 999, "total": 10})
    verifier = _verifier(transport)

    snapshot = await verifier.verify("mistral:mistral-small")

    assert snapshot.remaining == 7.0


async def test_wrong_contract_field_fails_even_when_lookalikes_present() -> None:
    """The declared v2 field is absent while a plausible lookalike from the old
    guess list is present: the verifier must raise, never adopt the lookalike."""
    transport = _mock_transport({"remaining": 5})
    verifier = MistralAdminApiVerifier(
        admin_api_key="admin-key",
        schema=MistralRateLimitSchema(version="v2", remaining_field="requests_remaining"),
        transport=transport,
    )

    with pytest.raises(MistralSchemaContractError, match="requests_remaining"):
        await verifier.verify("mistral:mistral-small")


async def test_missing_declared_field_names_keys_and_version() -> None:
    transport = _mock_transport({"some_other_field": 1})
    verifier = _verifier(transport)

    with pytest.raises(MistralSchemaContractError, match="confirmed-2026-field-study"):
        await verifier.verify("mistral:mistral-small")


@pytest.mark.parametrize(
    "bad_value",
    ["42", None, True, [42], {"n": 42}],
)
async def test_non_numeric_declared_field_fails(bad_value: object) -> None:
    transport = _mock_transport({"remaining": bad_value})
    verifier = _verifier(transport)

    with pytest.raises(MistralSchemaContractError, match="JSON number"):
        await verifier.verify("mistral:mistral-small")


@pytest.mark.parametrize("bad_value", [-1])
async def test_out_of_range_declared_field_fails(bad_value: float) -> None:
    transport = _mock_transport({"remaining": bad_value})
    verifier = _verifier(transport)

    with pytest.raises(MistralSchemaContractError, match="finite non-negative"):
        await verifier.verify("mistral:mistral-small")


@pytest.mark.parametrize("bad_value", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_declared_field_fails_at_the_parser(bad_value: float) -> None:
    """Non-finite sentinels cannot ride through httpx's JSON encoder, so these
    pin the parser directly: inf/nan are never a usable remaining quota."""
    with pytest.raises(MistralSchemaContractError, match="finite non-negative"):
        _extract_remaining({"remaining": bad_value}, SCHEMA)


async def test_non_object_payload_fails() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[{"remaining": 1}]))
    verifier = _verifier(transport)

    with pytest.raises(MistralSchemaContractError, match="JSON object"):
        await verifier.verify("mistral:mistral-small")


async def test_verify_raises_on_http_error() -> None:
    transport = _mock_transport({"error": "unauthorized"}, status_code=401, expected_key="bad-key")
    verifier = MistralAdminApiVerifier(admin_api_key="bad-key", schema=SCHEMA, transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        await verifier.verify("mistral:mistral-small")
