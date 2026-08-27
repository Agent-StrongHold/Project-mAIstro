"""Configuration sub-models for provider tiers and compute budgets."""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel


class Tier(IntEnum):
    """Compute tiers — higher tier = more capable model + more retries."""

    QUICK = 1  # Fast, cheap — single-shot with small model
    STANDARD = 2  # Default — good model, moderate retries
    THOROUGH = 3  # Multi-attempt with voting/ensemble
    ULTRA = 4  # Parallel generation + consensus voting (Ultra Think)


class TierConfig(BaseModel):
    """Per-tier model and retry configuration."""

    tier: Tier
    model: str
    max_retries: int = 3
    temperature: float = 0.0
    parallel_generations: int = 1  # >1 for ensemble (tier 3-4)
    timeout: int = 120  # LLM call timeout in seconds
    max_llm_retries: int = 3  # retries for transient LLM failures
    initial_backoff: float = 1.0  # base delay for exponential backoff


def get_default_tiers() -> dict[Tier, TierConfig]:
    """Build tier configs from the effective deployment model settings.

    This is a function (not a module-level constant) so it picks up
    settings that may be loaded after import time.  An unset tier inherits
    ``DEFAULT_MODEL``.  Local Ollama models are therefore selected only when
    an operator names one explicitly, rather than being a hidden fallback in
    an otherwise remote-gateway deployment.
    """
    from maistro.config.settings import get_settings

    settings = get_settings()
    overrides = {
        Tier.QUICK: settings.tier_1_model,
        Tier.STANDARD: settings.tier_2_model,
        Tier.THOROUGH: settings.tier_3_model,
        Tier.ULTRA: settings.tier_4_model,
    }

    return {
        Tier.QUICK: TierConfig(
            tier=Tier.QUICK,
            model=overrides[Tier.QUICK] or settings.default_model,
            max_retries=1,
            temperature=0.0,
        ),
        Tier.STANDARD: TierConfig(
            tier=Tier.STANDARD,
            model=overrides[Tier.STANDARD] or settings.default_model,
            max_retries=3,
            temperature=0.0,
        ),
        Tier.THOROUGH: TierConfig(
            tier=Tier.THOROUGH,
            model=overrides[Tier.THOROUGH] or settings.default_model,
            max_retries=5,
            temperature=0.3,
            parallel_generations=1,
        ),
        Tier.ULTRA: TierConfig(
            tier=Tier.ULTRA,
            model=overrides[Tier.ULTRA] or settings.default_model,
            max_retries=5,
            temperature=0.5,
            parallel_generations=1,
        ),
    }


# Backwards-compat alias — callers that imported DEFAULT_TIERS will get
# a lazy-loading wrapper. New code should call get_default_tiers() directly.
class _LazyTiers:
    """Dict-like proxy that calls get_default_tiers() on first access."""

    def __init__(self) -> None:
        self._cache: dict[Tier, TierConfig] | None = None

    def _ensure(self) -> dict[Tier, TierConfig]:
        if self._cache is None:
            self._cache = get_default_tiers()
        return self._cache

    def __getitem__(self, key: Tier) -> TierConfig:
        return self._ensure()[key]

    def __contains__(self, key: object) -> bool:
        return key in self._ensure()


DEFAULT_TIERS: _LazyTiers = _LazyTiers()
