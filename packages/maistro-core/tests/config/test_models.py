"""Effective tier-model precedence is part of the deployment contract."""

from __future__ import annotations

import pytest

from maistro.config.models import Tier, get_default_tiers
from maistro.config.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DEFAULT_MODEL",
        "TIER_1_MODEL",
        "TIER_2_MODEL",
        "TIER_3_MODEL",
        "TIER_4_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def test_default_model_is_the_fallback_for_every_unset_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_MODEL", "gateway/deployed-model")
    get_settings.cache_clear()

    tiers = get_default_tiers()

    assert {config.model for config in tiers.values()} == {"gateway/deployed-model"}


def test_explicit_tier_overrides_take_precedence_and_other_tiers_inherit_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_MODEL", "gateway/default")
    monkeypatch.setenv("TIER_1_MODEL", "gateway/fast")
    monkeypatch.setenv("TIER_4_MODEL", "gateway/most-capable")
    get_settings.cache_clear()

    tiers = get_default_tiers()

    assert tiers[Tier.QUICK].model == "gateway/fast"
    assert tiers[Tier.STANDARD].model == "gateway/default"
    assert tiers[Tier.THOROUGH].model == "gateway/default"
    assert tiers[Tier.ULTRA].model == "gateway/most-capable"


def test_ollama_is_used_only_when_explicitly_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_MODEL", "gateway/default")
    monkeypatch.setenv("TIER_2_MODEL", "ollama/qwen2.5-coder:32b")
    get_settings.cache_clear()

    tiers = get_default_tiers()

    assert tiers[Tier.STANDARD].model == "ollama/qwen2.5-coder:32b"
    assert all(
        config.model == "gateway/default"
        for tier, config in tiers.items()
        if tier is not Tier.STANDARD
    )
