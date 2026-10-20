"""Mistral Admin API `QuotaVerifier` — UNSUPPORTED until the response schema is
confirmed; must never be wired on the strength of field-name guessing.

Status (#1205): nothing in production imports this module — it stays unwired.
Wiring it requires confirming the actual reply shape of
`GET https://console.mistral.ai/api/admin/rate-limit` against a real Admin
Console API key and recording that contract explicitly. What *is* confirmed:
the endpoint exists, requires a **separate Admin Console API key** (not the
regular completions key), and is authenticated via an `x-api-key` header.
Mistral does not publish a documented JSON response schema for the endpoint.

Earlier revisions guessed among four plausible "remaining" field names and
accepted the first match — an unconfirmed schema must never be papered over
that way: the first match of a guess list is exactly how a wrong field (e.g. a
monthly token budget read as remaining requests) becomes quota truth. The
guessing is gone. The verifier now requires the caller to supply a
`MistralRateLimitSchema` — an explicit shape/version contract naming the one
remaining-quota field — and parses strictly against it: the field must be
present, a JSON number (bool rejected), finite, and non-negative, or the
verification fails with `MistralSchemaContractError` instead of fabricating a
snapshot. This verifier is a read-only observability input for reconciliation
(ADR-085, #56); it is not, and must not become, an enforcement or accounting
authority beside the canonical Invocation recording (#718).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import httpx

from maistro.http import shared_client
from maistro.quota.rate_profile import LimitUnit
from maistro.quota.reconciliation import ProviderQuotaSnapshot

_DEFAULT_BASE_URL = "https://console.mistral.ai/api/admin"


class MistralSchemaContractError(RuntimeError):
    """The response did not match the explicitly declared schema contract."""


@dataclass(frozen=True)
class MistralRateLimitSchema:
    """The confirmed response-shape contract for the Admin rate-limit endpoint.

    `version` identifies *which* confirmed shape the verifier parses (bump it
    when Mistral's reply shape changes and re-confirm against a real response);
    `remaining_field` names the one field that carries the remaining-quota
    number. There is deliberately no candidate list and no fallback: if the
    named field is absent or malformed, verification fails loudly.
    """

    version: str
    remaining_field: str


def _extract_remaining(payload: Any, schema: MistralRateLimitSchema) -> float:
    """Parse `schema.remaining_field` out of `payload`, strictly.

    Every deviation from the declared contract raises — a missing field, a
    string masquerading as a number, a boolean, NaN/infinity, or a negative
    value can never be silently reinterpreted as a usable remaining quota.
    """
    if not isinstance(payload, dict):
        raise MistralSchemaContractError(
            f"Mistral rate-limit schema {schema.version!r}: expected a JSON object, "
            f"got {type(payload).__name__}; payload={payload!r}"
        )
    if schema.remaining_field not in payload:
        raise MistralSchemaContractError(
            f"Mistral rate-limit schema {schema.version!r}: field "
            f"{schema.remaining_field!r} absent from response (keys="
            f"{sorted(payload)}); the declared contract does not match the "
            "endpoint's actual shape — re-confirm the schema before wiring"
        )
    value = payload[schema.remaining_field]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MistralSchemaContractError(
            f"Mistral rate-limit schema {schema.version!r}: field "
            f"{schema.remaining_field!r} must be a JSON number, got "
            f"{type(value).__name__} ({value!r})"
        )
    remaining = float(value)
    if not math.isfinite(remaining) or remaining < 0:
        raise MistralSchemaContractError(
            f"Mistral rate-limit schema {schema.version!r}: field "
            f"{schema.remaining_field!r} must be a finite non-negative number, "
            f"got {value!r}"
        )
    return remaining


class MistralAdminApiVerifier:
    """Calls Mistral's Admin Console rate-limit endpoint against an explicit,
    caller-supplied schema contract. See the module docstring: unwired until
    the contract is confirmed against a real response."""

    def __init__(
        self,
        admin_api_key: str,
        *,
        schema: MistralRateLimitSchema,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._admin_api_key = admin_api_key
        self._schema = schema
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport  # test seam: inject an httpx.MockTransport

    async def verify(self, scope_key: str) -> ProviderQuotaSnapshot:
        headers = {"x-api-key": self._admin_api_key}
        async with shared_client(timeout=self._timeout, transport=self._transport) as client:
            response = await client.get(f"{self._base_url}/rate-limit", headers=headers)
            response.raise_for_status()
            payload = response.json()

        remaining = _extract_remaining(payload, self._schema)

        return ProviderQuotaSnapshot(
            scope_key=scope_key,
            unit=LimitUnit.REQUESTS,
            remaining=remaining,
            checked_at=time.time(),
        )


__all__ = [
    "MistralAdminApiVerifier",
    "MistralRateLimitSchema",
    "MistralSchemaContractError",
]
