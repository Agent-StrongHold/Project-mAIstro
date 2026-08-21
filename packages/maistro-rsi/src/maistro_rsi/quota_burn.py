"""Quota-aware scheduling: discover the models exposed by the connected
LiteLLM instance and route RSI work toward whichever ones have the most idle
free-tier headroom — so unused token allowances get exercised before they
expire instead of sitting idle while a handful of default models get hammered.

Builds on `maistro.quota` (per-provider, per-billing-cycle usage tracking) and
`maistro.config.settings.LiteLLMSettings` (connection details) rather than
inventing a parallel accounting system.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from maistro.config.settings import get_settings
from maistro.http import shared_client
from maistro.quota.tracker import InMemoryQuotaTracker

logger = structlog.get_logger()


@dataclass
class ModelQuota:
    """A model's remaining headroom in the current billing cycle."""

    model: str
    provider: str
    free_tokens: int
    used_pct: float

    @property
    def headroom_tokens(self) -> int:
        return max(0, round(self.free_tokens * (1.0 - self.used_pct)))


async def discover_models(base_url: str | None = None, api_key: str | None = None) -> list[str]:
    """List model ids exposed by the connected LiteLLM instance (`/v1/models`)."""
    settings = get_settings()
    url = (base_url or settings.litellm.base_url).rstrip("/") + "/v1/models"
    headers = {"Authorization": f"Bearer {api_key or settings.litellm.master_key}"}

    async with shared_client(timeout=15.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()

    models = [entry["id"] for entry in payload.get("data", []) if "id" in entry]
    await logger.ainfo("rsi_models_discovered", count=len(models))
    return models


def _provider_of(model: str) -> str:
    """LiteLLM model ids are typically `provider/model-name`; fall back to the whole id."""
    return model.split("/")[0] if "/" in model else model


async def rank_models_by_headroom(
    models: list[str],
    tracker: InMemoryQuotaTracker,
    *,
    billing_cycle: str = "monthly",
    free_tokens_per_provider: dict[str, int] | None = None,
    default_free_tokens: int = 1_000_000,
) -> list[ModelQuota]:
    """Rank models by remaining free-tier headroom, most idle first.

    `free_tokens_per_provider` should reflect each provider's actual free-tier
    allowance (account-specific — there's no universal API for it); anything
    not listed falls back to `default_free_tokens` so newly-added providers
    still get scheduled sensibly rather than being skipped.
    """
    free_tokens_per_provider = free_tokens_per_provider or {}
    ranked: list[ModelQuota] = []

    for model in models:
        provider = _provider_of(model)
        free_tokens = free_tokens_per_provider.get(provider, default_free_tokens)
        used_pct = await tracker.get_usage_pct(provider, billing_cycle, free_tokens)
        ranked.append(
            ModelQuota(model=model, provider=provider, free_tokens=free_tokens, used_pct=used_pct)
        )

    ranked.sort(key=lambda m: m.headroom_tokens, reverse=True)
    return ranked


class QuotaBurnScheduler:
    """Routes successive RSI cycles toward whichever model has the most idle headroom.

    This is the "burn down free tokens" mechanism: rather than round-robin or
    sticking to one default model, each cycle re-ranks by current usage and
    picks the most under-utilized option, so allowances that would otherwise
    expire unused get exercised — while `free_tokens_per_provider` caps still
    prevent any provider from being pushed over its actual budget.
    """

    def __init__(
        self,
        tracker: InMemoryQuotaTracker,
        *,
        billing_cycle: str = "monthly",
        free_tokens_per_provider: dict[str, int] | None = None,
    ) -> None:
        self._tracker = tracker
        self._billing_cycle = billing_cycle
        self._free_tokens_per_provider = free_tokens_per_provider or {}

    async def next_model(self, available_models: list[str]) -> str | None:
        if not available_models:
            return None
        ranked = await rank_models_by_headroom(
            available_models,
            self._tracker,
            billing_cycle=self._billing_cycle,
            free_tokens_per_provider=self._free_tokens_per_provider,
        )
        return ranked[0].model if ranked else None

    async def record_attempt(self, model: str, input_tokens: int, output_tokens: int) -> None:
        await self._tracker.record_usage(
            _provider_of(model), self._billing_cycle, input_tokens, output_tokens
        )
