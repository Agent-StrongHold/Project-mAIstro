"""Effective tier-model precedence is part of the deployment contract."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from maistro.config.models import Tier, get_default_tiers


def _settings(
    *,
    default: str,
    tier_1: str = "",
    tier_2: str = "",
    tier_3: str = "",
    tier_4: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        default_model=default,
        tier_1_model=tier_1,
        tier_2_model=tier_2,
        tier_3_model=tier_3,
        tier_4_model=tier_4,
    )


def test_default_model_is_the_fallback_for_every_unset_tier() -> None:
    with patch(
        "maistro.config.settings.get_settings",
        return_value=_settings(default="gateway/deployed-model"),
    ):
        tiers = get_default_tiers()

    assert {config.model for config in tiers.values()} == {"gateway/deployed-model"}


def test_explicit_tier_overrides_take_precedence_and_other_tiers_inherit_default() -> None:
    with patch(
        "maistro.config.settings.get_settings",
        return_value=_settings(
            default="gateway/default",
            tier_1="gateway/fast",
            tier_4="gateway/most-capable",
        ),
    ):
        tiers = get_default_tiers()

    assert tiers[Tier.QUICK].model == "gateway/fast"
    assert tiers[Tier.STANDARD].model == "gateway/default"
    assert tiers[Tier.THOROUGH].model == "gateway/default"
    assert tiers[Tier.ULTRA].model == "gateway/most-capable"


def test_ollama_is_used_only_when_explicitly_configured() -> None:
    with patch(
        "maistro.config.settings.get_settings",
        return_value=_settings(
            default="gateway/default",
            tier_2="ollama/qwen2.5-coder:32b",
        ),
    ):
        tiers = get_default_tiers()

    assert tiers[Tier.STANDARD].model == "ollama/qwen2.5-coder:32b"
    assert all(
        config.model == "gateway/default"
        for tier, config in tiers.items()
        if tier is not Tier.STANDARD
    )
