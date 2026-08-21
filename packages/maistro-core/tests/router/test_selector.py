"""Coverage for maistro.router.selector.RouterEngine (was 25%).

Exercises the full filter -> score -> rank -> fallback pipeline end to end,
including the quota-reserve-vs-truly-empty branch split and the human-readable
reason string, with assertions on the actual selected model and its score
ordering -- not just "a selection object came back".
"""

from __future__ import annotations

import pytest

from maistro.router.selector import RouterEngine
from maistro.types.config import RoutingConfig
from maistro.types.errors import NoModelsError, QuotaReserveError
from maistro.types.intent import Intent
from maistro.types.model import ModelConfig, ProviderConfig


class _StubQuotaTracker:
    """RouterEngine only stores the tracker; select()/select_with_usage() don't
    call back into it directly in the sync paths exercised here."""


def _engine() -> RouterEngine:
    return RouterEngine(_StubQuotaTracker())


def _routing_config(**overrides) -> RoutingConfig:
    return RoutingConfig(**overrides)


# ─── select_with_usage: happy path, ranking ──────────────────────────────────


def test_selects_highest_scoring_candidate_among_eligible_models():
    engine = _engine()
    models = {
        "cheap-low-quality": ModelConfig(provider="p", tier="small", quality=0.3),
        "expensive-high-quality": ModelConfig(provider="p", tier="small", quality=0.95),
    }
    providers = {"p": ProviderConfig(status="active", free_tokens=1_000_000)}
    intent = Intent(tier="P2")

    result = engine.select_with_usage(
        intent, models, providers, _routing_config(quality_weight=0.6, cost_weight=0.0), {}
    )

    assert result.model_id == "expensive-high-quality"
    assert result.score > 0
    assert len(result.candidates) == 2
    # Candidates must be sorted descending by score.
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
    assert result.candidates[0].model_id == "expensive-high-quality"


def test_reason_string_includes_task_complexity_tier_and_runner_up():
    engine = _engine()
    models = {
        "a": ModelConfig(provider="p", tier="small", quality=0.9),
        "b": ModelConfig(provider="p", tier="small", quality=0.5),
    }
    providers = {"p": ProviderConfig(status="active", free_tokens=1_000_000)}
    intent = Intent(task_type="codegen", complexity="complex", tier="P1")

    result = engine.select_with_usage(intent, models, providers, _routing_config(), {})

    assert "task=codegen" in result.reason
    assert "complexity=complex" in result.reason
    assert "tier=P1" in result.reason
    assert "quality=" in result.reason
    assert "runner_up=b" in result.reason


def test_single_candidate_reason_has_no_runner_up():
    engine = _engine()
    models = {"only": ModelConfig(provider="p", tier="small", quality=0.7)}
    providers = {"p": ProviderConfig(status="active", free_tokens=1_000_000)}

    result = engine.select_with_usage(Intent(), models, providers, _routing_config(), {})

    assert "runner_up" not in result.reason


def test_litellm_id_falls_back_to_model_id_when_unset():
    engine = _engine()
    models = {"my-model": ModelConfig(provider="p", tier="small", litellm_id="")}
    providers = {"p": ProviderConfig(status="active", free_tokens=1_000_000)}

    result = engine.select_with_usage(Intent(), models, providers, _routing_config(), {})
    assert result.litellm_id == "my-model"


# ─── select(): thin wrapper around select_with_usage with empty usage ───────


def test_select_delegates_to_select_with_usage_with_empty_usage_pcts():
    engine = _engine()
    models = {"m": ModelConfig(provider="p", tier="small")}
    providers = {"p": ProviderConfig(status="active", free_tokens=1_000_000)}

    via_select = engine.select(Intent(), models, providers, _routing_config())
    via_select_with_usage = engine.select_with_usage(
        Intent(), models, providers, _routing_config(), {}
    )
    assert via_select.model_id == via_select_with_usage.model_id
    assert via_select.score == via_select_with_usage.score


# ─── No filtered candidates: quota-reserve vs truly-empty branch split ──────


def test_all_candidates_in_quota_reserve_raises_quota_reserve_error():
    engine = _engine()
    models = {"m": ModelConfig(provider="p", tier="small")}
    providers = {"p": ProviderConfig(status="active")}
    intent = Intent(tier="P2")

    # 96% usage with default 5% reserve and non-P0 tier -> filtered by reserve,
    # but the model WOULD be eligible at reserve_pct=0 -> QuotaReserveError, not fallback.
    with pytest.raises(QuotaReserveError, match="P0 to override"):
        engine.select_with_usage(
            intent, models, providers, _routing_config(reserve_pct=0.05), {"p": 0.96}
        )


def test_no_eligible_models_at_all_falls_back_to_best_quality_active_model():
    engine = _engine()
    models = {
        "wrong-modality": ModelConfig(
            provider="p", tier="small", modality="image_gen", quality=0.99
        ),
        "best-active": ModelConfig(provider="p", tier="small", quality=0.6),
    }
    providers = {"p": ProviderConfig(status="active", free_tokens=1_000_000)}
    intent = Intent(task_type="chat", min_tier="frontier")  # tier filter excludes both via min_tier

    result = engine.select_with_usage(intent, models, providers, _routing_config(), {})

    # Fallback ignores filters entirely and picks best quality active model
    # regardless of modality/tier eligibility.
    assert result.model_id == "wrong-modality"
    assert result.score == 0.0
    assert result.reason == "fallback — no models matched filters"
    assert result.candidates == ()


def test_fallback_skips_inactive_providers():
    engine = _engine()
    models = {
        "inactive-high-quality": ModelConfig(provider="dead", tier="small", quality=0.99),
        "active-lower-quality": ModelConfig(provider="alive", tier="small", quality=0.4),
    }
    providers = {
        "dead": ProviderConfig(status="disabled"),
        "alive": ProviderConfig(status="active"),
    }
    intent = Intent(min_tier="frontier")  # forces zero filtered candidates

    result = engine.select_with_usage(intent, models, providers, _routing_config(), {})
    assert result.model_id == "active-lower-quality"


def test_fallback_raises_no_models_error_when_no_active_models_exist():
    engine = _engine()
    models = {"m": ModelConfig(provider="p", tier="small")}
    providers = {"p": ProviderConfig(status="disabled")}
    intent = Intent(min_tier="frontier")

    with pytest.raises(NoModelsError, match="No active models"):
        engine.select_with_usage(intent, models, providers, _routing_config(), {})


def test_empty_models_dict_falls_back_and_raises_no_models_error():
    engine = _engine()
    with pytest.raises(NoModelsError):
        engine.select_with_usage(Intent(), {}, {}, _routing_config(), {})
