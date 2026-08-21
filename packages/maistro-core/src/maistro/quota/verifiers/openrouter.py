"""OpenRouter `QuotaVerifier`s — the one provider in the roster with real,
standalone balance/usage endpoints:

* `OpenRouterKeyVerifier`  — `GET /api/v1/key`, zero-cost, uses the same bearer
  key as chat completions; reports the remaining dollar-credit balance.
* `OpenRouterActivityVerifier` — `GET /api/v1/activity`, per-model request /
  token / cost ground truth. Requires a MANAGEMENT (provisioning) key — the
  inference key gets 403 here. This is the richer signal: it's how you see
  which models a run actually consumed, and reconcile free-tier request usage
  (free models report cost 0), which no response header exposes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from maistro.http import shared_client
from maistro.quota.rate_profile import LimitUnit
from maistro.quota.reconciliation import ProviderQuotaSnapshot

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _utc_today() -> str:
    """Current UTC calendar day as ``YYYY-MM-DD`` — the day the :free caps reset on."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


# OpenRouter `:free`-model daily request caps (per the docs): keyed to LIFETIME
# credits PURCHASED, not current balance — >= $10 purchased raises the daily cap
# and it stays raised as the balance is spent down. Only a NEGATIVE balance
# disables free models (402). RPM is a flat 20 for all free models.
FREE_MODEL_RPM = 20
FREE_MODEL_RPD_NO_CREDITS = 50
FREE_MODEL_RPD_WITH_CREDITS = 1000
FREE_MODEL_CREDITS_THRESHOLD_USD = 10.0


class OpenRouterKeyVerifier:
    """Calls `GET /api/v1/key` and reports the account's remaining credit balance."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport  # test seam: inject an httpx.MockTransport

    async def verify(self, scope_key: str) -> ProviderQuotaSnapshot:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with shared_client(timeout=self._timeout, transport=self._transport) as client:
            response = await client.get(f"{self._base_url}/key", headers=headers)
            response.raise_for_status()
            payload = response.json().get("data", {})

        limit_remaining = payload.get("limit_remaining")
        # `null` means "unlimited" per OpenRouter's docs, not "zero left" —
        # surfacing that distinction is the caller's job, not this verifier's;
        # infinity keeps "unconstrained" and "exhausted" from looking the same.
        remaining = float(limit_remaining) if limit_remaining is not None else float("inf")

        return ProviderQuotaSnapshot(
            scope_key=scope_key,
            unit=LimitUnit.CREDITS_USD,
            remaining=remaining,
            checked_at=time.time(),
        )


@dataclass(frozen=True)
class ModelUsage:
    """One model's usage over the activity window (from `GET /api/v1/activity`).
    Free models report ``cost_usd == 0.0`` — the only marker distinguishing free
    from paid usage, since the model id carries no ``:free`` suffix here."""

    model: str
    requests: int
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int


class OpenRouterActivityVerifier:
    """Ground truth from `GET /api/v1/activity` (per-model request/token/cost).

    Requires a MANAGEMENT/provisioning key — the inference key returns 403.
    ``verify()`` reports the day's REMAINING free-tier requests (free rows are
    those with ``cost_usd == 0``), against the applicable free-model daily cap
    (default: the >=$10-purchased tier of 1000/day; set ``free_rpd_limit`` from
    the account's tier when it isn't). ``fetch_activity()`` exposes the full
    per-model breakdown for observability tools.
    """

    def __init__(
        self,
        management_key: str,
        *,
        free_rpd_limit: int = FREE_MODEL_RPD_WITH_CREDITS,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._management_key = management_key
        self._free_rpd_limit = free_rpd_limit
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport  # test seam: inject an httpx.MockTransport

    async def fetch_activity(self, *, date: str | None = None) -> list[ModelUsage]:
        """Per-model usage, aggregated (a model can appear on multiple rows —
        per date/endpoint), sorted most-requests first.

        ``date`` (UTC ``YYYY-MM-DD``) scopes the query to a single day. This is
        REQUIRED for a same-day remaining-quota read: OpenRouter's default
        ``/activity`` response covers the last 30 COMPLETED UTC days and EXCLUDES
        the current day, so summing it as "today" both counts stale history and
        misses requests already made today."""
        headers = {"Authorization": f"Bearer {self._management_key}"}
        params = {"date": date} if date else None
        async with shared_client(timeout=self._timeout, transport=self._transport) as client:
            response = await client.get(
                f"{self._base_url}/activity", headers=headers, params=params
            )
            response.raise_for_status()
            rows = response.json().get("data", [])

        agg: dict[str, ModelUsage] = {}
        for row in rows:
            model = row.get("model") or row.get("model_permaslug") or "unknown"
            reqs = int(row.get("requests") or 0)
            cost = float(row.get("usage") or 0.0)
            ptok = int(row.get("prompt_tokens") or 0)
            ctok = int(row.get("completion_tokens") or 0)
            prev = agg.get(model)
            if prev is None:
                agg[model] = ModelUsage(model, reqs, cost, ptok, ctok)
            else:
                agg[model] = ModelUsage(
                    model,
                    prev.requests + reqs,
                    prev.cost_usd + cost,
                    prev.prompt_tokens + ptok,
                    prev.completion_tokens + ctok,
                )
        return sorted(agg.values(), key=lambda u: u.requests, reverse=True)

    async def verify(
        self, scope_key: str = "openrouter:free-requests", *, date: str | None = None
    ) -> ProviderQuotaSnapshot:
        # The :free daily cap resets at 00:00 UTC, so "remaining today" must count
        # ONLY today's free requests — scope the query to the current UTC day (the
        # default 30-day window would badly over- or under-count).
        rows = await self.fetch_activity(date=date or _utc_today())
        free_used = sum(u.requests for u in rows if u.cost_usd == 0.0)
        remaining = max(0.0, float(self._free_rpd_limit) - free_used)
        return ProviderQuotaSnapshot(
            scope_key=scope_key,
            unit=LimitUnit.REQUESTS,
            remaining=remaining,
            checked_at=time.time(),
        )
