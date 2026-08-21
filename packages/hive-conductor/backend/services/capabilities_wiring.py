"""Register app-supplied capability providers and apply operator activation.

The core `Container` ships the canonical slots + dependency-free baselines
(the approval inbox). hive-conductor adds the providers it has the config to
build — the host-health monitor/action behind an httpx seam — and applies the
operator's enabled/active choices from `SettingsModel.capabilities`.

Kept deliberately resilient: bad config or settings must never crash startup.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from maistro.capabilities.http_client import HttpxAsyncHttp
from maistro.capabilities.providers.host_health import HostHealthAction, HostHealthMonitor
from maistro.capabilities.providers.self_repair import RuleBasedRepair

if TYPE_CHECKING:
    from config import Settings
    from models.schemas import SettingsModel

    from maistro.capabilities.registry import CapabilityRegistry

logger = logging.getLogger("hive.capabilities")

_T = TypeVar("_T")


class _VaultLike(Protocol):
    def use(self, name: str, callback: Callable[[str], _T]) -> _T: ...


_TOKEN_KEY = "HOST_HEALTH_TOKEN"


def wire_capabilities(
    registry: CapabilityRegistry,
    *,
    settings_model: SettingsModel,
    config: Settings,
    vault: _VaultLike | None = None,
) -> None:
    """Register host-health providers (if configured) then apply activation."""
    _register_host_health(registry, config, vault)
    _apply_activation(registry, settings_model)


def _resolve_token(config: Settings, vault: _VaultLike | None) -> str | None:
    """Prefer the vault secret; fall back to the env-backed config setting."""
    if vault is not None:
        try:
            return vault.use(_TOKEN_KEY, lambda s: s)
        except Exception:  # secret missing / vault unavailable → fall back
            logger.debug("host-health token not in vault; using config fallback")
    if config.host_health_token is not None:
        return config.host_health_token.get_secret_value()
    return None


def _register_host_health(
    registry: CapabilityRegistry, config: Settings, vault: _VaultLike | None
) -> None:
    url = (config.host_health_url or "").strip()
    if not url:
        logger.info("host_health_url unset — infra_* slots stay SAFE_NOOP")
        return
    token = _resolve_token(config, vault)
    http = HttpxAsyncHttp(url, token=token)
    inbox = registry.provider("approval", "inbox")
    registry.register(HostHealthMonitor(http))
    registry.register(HostHealthAction(http, autonomy=config.infra_autonomy, approval=inbox))
    logger.info("registered host-health infra providers -> %s", url)
    _register_self_repair(registry, config)


def _register_self_repair(registry: CapabilityRegistry, config: Settings) -> None:
    """Register the self_repair provider once infra_monitor/infra_action exist (SPEC-188)."""
    monitor = registry.provider("infra_monitor", "host_health")
    action = registry.provider("infra_action", "host_health")
    if monitor is None or action is None:
        return
    registry.register(
        RuleBasedRepair(
            infra_monitor=monitor,
            infra_action=action,
            autonomy=config.infra_autonomy,
        )
    )
    logger.info("registered self_repair provider (autonomy=%s)", config.infra_autonomy)


async def run_self_repair_once(registry: CapabilityRegistry) -> Any | None:
    """Resolve the self_repair slot and run one cycle, or None if unavailable.

    Resolution is the kill-switch: a disabled slot (or unavailable provider)
    resolves to None (SAFE_NOOP), so nothing runs — no special-casing needed.
    """
    provider = await registry.resolve("self_repair")
    if provider is None or not hasattr(provider, "run_once"):
        return None
    return await provider.run_once()


def _apply_activation(registry: CapabilityRegistry, settings_model: SettingsModel) -> None:
    for slot, setting in (settings_model.capabilities or {}).items():
        try:
            registry.set_enabled(slot, setting.enabled)
            if setting.active_provider and setting.active_provider in registry.installed(slot):
                registry.activate(slot, setting.active_provider)
        except KeyError:
            logger.warning("settings reference unknown capability slot %r — ignored", slot)
