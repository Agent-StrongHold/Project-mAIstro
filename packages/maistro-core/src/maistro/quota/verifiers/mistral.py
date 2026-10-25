"""Mistral Admin API `QuotaVerifier` — checks remaining request headroom via
Mistral's Admin Console rate-limit endpoint.

**Response schema caveat (read before trusting this blindly):** unlike
OpenRouter's `/api/v1/key` (`openrouter.py`, confirmed against OpenRouter's own
published docs), Mistral does not publish a documented JSON response schema
for `GET https://console.mistral.ai/api/admin/rate-limit`. What *is* confirmed:
the endpoint exists, requires a **separate Admin Console API key** (not the
regular completions key), and is authenticated via an `x-api-key` header —
Mistral's public docs describe the rate-limit dimensions themselves (RPS, TPM,
tokens-per-month) and an Admin Console "Limits" page, but not this endpoint's
exact reply shape.

So the field-extraction here is deliberately defensive rather than confident:
it checks a short list of plausible "remaining" field names and raises — it
does not fabricate a snapshot — if none match. Treat this as a best-effort
starting point to verify against a real response the first time it's
exercised with actual Admin API credentials, and extend
`_REMAINING_FIELD_CANDIDATES` once the real shape is known.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from maistro.http import shared_client
from maistro.quota.rate_profile import LimitUnit
from maistro.quota.reconciliation import ProviderQuotaSnapshot

_DEFAULT_BASE_URL = "https://console.mistral.ai/api/admin"

# Checked in order; first match wins. See module docstring -- unconfirmed
# against a real response, extend/reorder once the actual shape is known.
_REMAINING_FIELD_CANDIDATES = (
    "remaining",
    "requests_remaining",
    "rate_limit_remaining",
    "remaining_requests",
)


def _extract_remaining(payload: dict[str, Any]) -> float | None:
    for field in _REMAINING_FIELD_CANDIDATES:
        if field in payload:
            try:
                return float(payload[field])
            except (TypeError, ValueError):
                return None
    return None


class MistralAdminApiVerifier:
    """Calls Mistral's Admin Console rate-limit endpoint with a **separate**
    Admin API key. See module docstring for the response-schema caveat."""

    def __init__(
        self,
        admin_api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._admin_api_key = admin_api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport  # test seam: inject an httpx.MockTransport

    async def verify(self, scope_key: str) -> ProviderQuotaSnapshot:
        headers = {"x-api-key": self._admin_api_key}
        async with shared_client(timeout=self._timeout, transport=self._transport) as client:
            response = await client.get(f"{self._base_url}/rate-limit", headers=headers)
            response.raise_for_status()
            payload = response.json()

        remaining = _extract_remaining(payload)
        if remaining is None:
            raise RuntimeError(
                "MistralAdminApiVerifier: response did not contain a recognized "
                f"remaining-quota field (checked {_REMAINING_FIELD_CANDIDATES}); "
                f"payload={payload!r} — verify the endpoint's actual response shape "
                "and update _REMAINING_FIELD_CANDIDATES"
            )

        return ProviderQuotaSnapshot(
            scope_key=scope_key,
            unit=LimitUnit.REQUESTS,
            remaining=remaining,
            checked_at=time.time(),
        )


__all__ = ["MistralAdminApiVerifier"]
