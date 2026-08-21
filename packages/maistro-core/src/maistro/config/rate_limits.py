"""Resolves a model alias (matching `models.toml`'s `alias` field, e.g.
`"cerebras-qwen-3-235b-a22b-2507"`) to a `quota.rate_profile.ModelRateProfile`,
reading the configured shapes from `MaistroYamlConfig.rate_profiles`.

`models.toml` itself has no Python loader (it's hive-conductor's model-comparison
reference table, not a config source) -- this module doesn't read it. It only
borrows its `alias` naming convention as the lookup key, since that's the string
a caller already has in hand when it needs a rate profile for a model.
"""

from __future__ import annotations

from maistro.config.settings import MaistroYamlConfig, ModelRateProfileConfig, get_yaml_config
from maistro.quota.rate_profile import ModelRateProfile, RateConstraint


def _to_rate_profile(cfg: ModelRateProfileConfig) -> ModelRateProfile:
    return ModelRateProfile(
        provider=cfg.provider,
        model=cfg.model,
        constraints=tuple(
            RateConstraint(unit=c.unit, window=c.window, limit=c.limit) for c in cfg.constraints
        ),
        scope_key_fields=tuple(cfg.scope_key_fields),
    )


def _guess_provider(alias: str) -> str:
    # models.toml's own convention is "{provider}-{model-name}" (e.g.
    # "sambanova-deepseek-r1-0528") -- a reasonable guess for an alias this
    # resolver has never seen configured, so the fallback profile's scope_key
    # still groups by something meaningful rather than the whole alias string.
    return alias.split("-", 1)[0] if "-" in alias else alias


def resolve_rate_profile(alias: str, config: MaistroYamlConfig | None = None) -> ModelRateProfile:
    """Look up `alias` among the configured rate profiles.

    An alias with no configured profile gets a permissive, no-constraints
    `ModelRateProfile` back (`cycles_remaining` then reports infinite headroom)
    rather than raising -- mirrors `quota_burn.py`'s existing "unknown provider
    still gets scheduled sensibly" philosophy. A model whose real limits
    haven't been configured yet shouldn't be refused work; it's simply
    unconstrained until someone adds its profile to `rate_profiles`.
    """
    cfg = config if config is not None else get_yaml_config()
    if cfg is not None:
        for profile_cfg in cfg.rate_profiles:
            if profile_cfg.model == alias:
                return _to_rate_profile(profile_cfg)
    return ModelRateProfile(provider=_guess_provider(alias), model=alias, constraints=())


__all__ = ["resolve_rate_profile"]
