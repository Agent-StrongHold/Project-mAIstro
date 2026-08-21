"""Tests for maistro.config.rate_limits — model-alias -> ModelRateProfile resolver."""

from __future__ import annotations

from maistro.config.rate_limits import resolve_rate_profile
from maistro.config.settings import MaistroYamlConfig, ModelRateProfileConfig, RateConstraintConfig
from maistro.quota.rate_profile import LimitUnit, LimitWindow


def _config_with(*profiles: ModelRateProfileConfig) -> MaistroYamlConfig:
    return MaistroYamlConfig(rate_profiles=list(profiles))


class TestResolveRateProfile:
    def test_unrecognized_alias_gets_permissive_fallback(self) -> None:
        profile = resolve_rate_profile("cerebras-qwen-3-235b-a22b-2507", config=_config_with())
        assert profile.constraints == ()
        assert profile.model == "cerebras-qwen-3-235b-a22b-2507"

    def test_unrecognized_alias_guesses_provider_from_prefix(self) -> None:
        profile = resolve_rate_profile("groq-moonshotai/kimi-k2", config=_config_with())
        assert profile.provider == "groq"

    def test_alias_with_no_hyphen_uses_whole_string_as_provider(self) -> None:
        profile = resolve_rate_profile("standalone", config=_config_with())
        assert profile.provider == "standalone"

    def test_matches_configured_profile_by_model_field(self) -> None:
        configured = ModelRateProfileConfig(
            provider="cerebras",
            model="cerebras-qwen-3-235b-a22b-2507",
            constraints=[
                RateConstraintConfig(unit=LimitUnit.REQUESTS, window=LimitWindow.DAY, limit=14_400),
                RateConstraintConfig(
                    unit=LimitUnit.TOTAL_TOKENS, window=LimitWindow.MINUTE, limit=60_000
                ),
            ],
        )
        profile = resolve_rate_profile(
            "cerebras-qwen-3-235b-a22b-2507", config=_config_with(configured)
        )
        assert profile.provider == "cerebras"
        assert len(profile.constraints) == 2
        assert profile.constraints[0].unit == LimitUnit.REQUESTS
        assert profile.constraints[0].limit == 14_400

    def test_falls_back_to_global_yaml_config_when_none_passed(self) -> None:
        from maistro.config.settings import set_yaml_config

        try:
            set_yaml_config(
                _config_with(ModelRateProfileConfig(provider="mistral", model="mistral-small"))
            )
            profile = resolve_rate_profile("mistral-small")
            assert profile.provider == "mistral"
        finally:
            set_yaml_config(None)

    def test_no_global_config_still_falls_back_permissively(self) -> None:
        from maistro.config.settings import set_yaml_config

        set_yaml_config(None)
        profile = resolve_rate_profile("some-unknown-alias")
        assert profile.constraints == ()

    def test_default_scope_key_fields_are_provider_and_model(self) -> None:
        configured = ModelRateProfileConfig(provider="groq", model="groq-kimi-k2")
        profile = resolve_rate_profile("groq-kimi-k2", config=_config_with(configured))
        assert profile.scope_key_fields == ("provider", "model")
