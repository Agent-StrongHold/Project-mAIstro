"""Coverage for maistro.router.filter (was 19%): modality/tier/quota/active filtering."""

from __future__ import annotations

from maistro.router.filter import (
    _modality_matches,
    _quota_allows,
    _tier_in_range,
    filter_candidates,
)
from maistro.types.intent import Intent
from maistro.types.model import ModelConfig, ProviderConfig

# ─── _modality_matches ────────────────────────────────────────────────────────


def test_modality_image_gen_requires_image_gen_model():
    assert _modality_matches("image_gen", "image_gen") is True
    assert _modality_matches("image_gen", "text") is False


def test_modality_embedding_requires_embedding_model():
    assert _modality_matches("embedding", "embedding") is True
    assert _modality_matches("embedding", "text") is False


def test_modality_text_task_excludes_image_and_embedding_models():
    assert _modality_matches("chat", "text") is True
    assert _modality_matches("chat", "image_gen") is False
    assert _modality_matches("chat", "embedding") is False


# ─── _tier_in_range ────────────────────────────────────────────────────────────


def test_tier_below_min_tier_rejected():
    intent = Intent(min_tier="medium")
    assert _tier_in_range("small", intent) is False


def test_tier_at_min_tier_accepted():
    intent = Intent(min_tier="medium")
    assert _tier_in_range("medium", intent) is True


def test_tier_above_max_tier_rejected():
    intent = Intent(min_tier="small", max_tier="medium")
    assert _tier_in_range("large", intent) is False


def test_tier_within_band_accepted():
    intent = Intent(min_tier="small", max_tier="large")
    assert _tier_in_range("medium", intent) is True


def test_no_max_tier_means_unbounded_above():
    intent = Intent(min_tier="small", max_tier=None)
    assert _tier_in_range("frontier", intent) is True


def test_unknown_tier_name_treated_as_rank_zero():
    intent = Intent(min_tier="small")
    assert _tier_in_range("nonexistent-tier", intent) is True  # rank 0 >= min rank 0
    intent2 = Intent(min_tier="medium")
    assert _tier_in_range("nonexistent-tier", intent2) is False  # rank 0 < min rank 1


# ─── _quota_allows ─────────────────────────────────────────────────────────────


def test_quota_full_usage_without_paygo_denied():
    provider = ProviderConfig(overage_cost_per_1k_input=0.0, overage_cost_per_1k_output=0.0)
    intent = Intent(tier="P2")
    assert _quota_allows(provider, usage_pct=1.0, intent=intent, reserve_pct=0.05) is False


def test_quota_full_usage_with_paygo_allowed():
    provider = ProviderConfig(overage_cost_per_1k_input=0.5)
    intent = Intent(tier="P2")
    assert _quota_allows(provider, usage_pct=1.0, intent=intent, reserve_pct=0.05) is True


def test_quota_within_reserve_band_p0_overrides_reserve():
    provider = ProviderConfig()
    intent = Intent(tier="P0")
    # 96% usage, 5% reserve -> would normally be blocked, but P0 overrides.
    assert _quota_allows(provider, usage_pct=0.96, intent=intent, reserve_pct=0.05) is True


def test_quota_within_reserve_band_non_p0_blocked():
    provider = ProviderConfig()
    intent = Intent(tier="P2")
    assert _quota_allows(provider, usage_pct=0.96, intent=intent, reserve_pct=0.05) is False


def test_quota_below_reserve_band_allowed():
    provider = ProviderConfig()
    intent = Intent(tier="P2")
    assert _quota_allows(provider, usage_pct=0.5, intent=intent, reserve_pct=0.05) is True


def test_quota_reserve_band_with_output_paygo_only_still_allowed():
    provider = ProviderConfig(overage_cost_per_1k_output=0.2)
    intent = Intent(tier="P2")
    assert _quota_allows(provider, usage_pct=0.96, intent=intent, reserve_pct=0.05) is True


# ─── filter_candidates (integration of the above) ─────────────────────────────


def _model(provider="openai", tier="medium", modality="text"):
    return ModelConfig(provider=provider, tier=tier, modality=modality)


def test_filter_excludes_models_with_unknown_provider():
    models = {"m1": _model(provider="ghost")}
    providers = {"openai": ProviderConfig(status="active")}
    assert filter_candidates(Intent(), models, providers) == []


def test_filter_excludes_inactive_provider():
    models = {"m1": _model()}
    providers = {"openai": ProviderConfig(status="disabled")}
    assert filter_candidates(Intent(), models, providers) == []


def test_filter_excludes_modality_mismatch():
    models = {"m1": _model(modality="embedding")}
    providers = {"openai": ProviderConfig(status="active")}
    assert filter_candidates(Intent(task_type="chat"), models, providers) == []


def test_filter_excludes_tier_out_of_range():
    models = {"m1": _model(tier="small")}
    providers = {"openai": ProviderConfig(status="active")}
    intent = Intent(min_tier="large")
    assert filter_candidates(intent, models, providers) == []


def test_filter_excludes_over_quota_provider():
    models = {"m1": _model()}
    providers = {"openai": ProviderConfig(status="active")}
    intent = Intent(tier="P2")
    result = filter_candidates(intent, models, providers, usage_pcts={"openai": 1.0})
    assert result == []


def test_filter_returns_matching_model_with_usage_pct():
    models = {"m1": _model()}
    providers = {"openai": ProviderConfig(status="active")}
    intent = Intent(tier="P2")
    result = filter_candidates(intent, models, providers, usage_pcts={"openai": 0.3})
    assert len(result) == 1
    model_id, model_cfg, _provider_cfg, usage_pct = result[0]
    assert model_id == "m1"
    assert model_cfg.provider == "openai"
    assert usage_pct == 0.3


def test_filter_missing_usage_pcts_defaults_to_zero():
    models = {"m1": _model()}
    providers = {"openai": ProviderConfig(status="active")}
    result = filter_candidates(Intent(tier="P2"), models, providers)
    assert result[0][3] == 0.0


def test_filter_multiple_models_only_eligible_ones_returned():
    models = {
        "ok": _model(provider="openai", tier="medium"),
        "wrong_provider": _model(provider="ghost"),
        "wrong_modality": _model(provider="openai", modality="embedding"),
    }
    providers = {"openai": ProviderConfig(status="active")}
    result = filter_candidates(Intent(task_type="chat", min_tier="small"), models, providers)
    assert [r[0] for r in result] == ["ok"]
