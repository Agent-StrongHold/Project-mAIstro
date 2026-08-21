"""Model filtering: modality, tier, quota, active status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.types.intent import TIER_ORDER

if TYPE_CHECKING:
    from maistro.types.intent import Intent
    from maistro.types.model import ModelConfig, ProviderConfig


def _modality_matches(task_type: str, model_modality: str) -> bool:
    """Whether a model's modality is compatible with the intent's task type."""
    if task_type == "image_gen":
        return model_modality == "image_gen"
    if task_type == "embedding":
        return model_modality == "embedding"
    return model_modality not in ("image_gen", "embedding")


def _tier_in_range(model_tier: str, intent: Intent) -> bool:
    """Whether ``model_tier`` falls within the intent's [min_tier, max_tier] band."""
    tier_rank = TIER_ORDER.get(model_tier, 0)
    if tier_rank < TIER_ORDER.get(intent.min_tier, 0):
        return False
    return not (intent.max_tier and tier_rank > TIER_ORDER.get(intent.max_tier, 99))


def _quota_allows(
    provider_cfg: ProviderConfig,
    usage_pct: float,
    intent: Intent,
    reserve_pct: float,
) -> bool:
    """Whether quota/reserve rules permit routing to this provider."""
    has_paygo = (
        provider_cfg.overage_cost_per_1k_input > 0 or provider_cfg.overage_cost_per_1k_output > 0
    )
    if usage_pct >= 1.0 and not has_paygo:
        return False
    return not (usage_pct >= (1.0 - reserve_pct) and intent.tier != "P0" and not has_paygo)


def filter_candidates(
    intent: Intent,
    models: dict[str, ModelConfig],
    providers: dict[str, ProviderConfig],
    *,
    usage_pcts: dict[str, float] | None = None,
    reserve_pct: float = 0.05,
) -> list[tuple[str, ModelConfig, ProviderConfig, float]]:
    """Filter models by modality, tier, quota, and active status.

    Returns list of (model_id, model_config, provider_config, usage_pct) tuples.
    """
    if usage_pcts is None:
        usage_pcts = {}

    result: list[tuple[str, ModelConfig, ProviderConfig, float]] = []

    for model_id, model_cfg in models.items():
        provider_name = model_cfg.provider
        provider_cfg = providers.get(provider_name)
        if provider_cfg is None or provider_cfg.status != "active":
            continue

        if not _modality_matches(intent.task_type, model_cfg.modality):
            continue

        if not _tier_in_range(model_cfg.tier, intent):
            continue

        usage_pct = usage_pcts.get(provider_name, 0.0)
        if not _quota_allows(provider_cfg, usage_pct, intent, reserve_pct):
            continue

        result.append((model_id, model_cfg, provider_cfg, usage_pct))

    return result
