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

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import InMemoryBindingStore
from maistro.capabilities.effect_context import CapabilityEffectContext, new_effect_context
from maistro.capabilities.http_client import HttpxAsyncHttp
from maistro.capabilities.providers.host_health import HostHealthAction, HostHealthMonitor
from maistro.capabilities.providers.self_repair import RuleBasedRepair
from maistro.capabilities.slots.infra import ActionResult, InfraAction
from maistro.capabilities.types import Unavailable

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
    effect_context: CapabilityEffectContext | None = None,
) -> None:
    """Register host-health providers (if configured) then apply activation."""
    _register_host_health(
        registry,
        config,
        vault,
        effect_context=effect_context or new_effect_context(),
    )
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
    registry: CapabilityRegistry,
    config: Settings,
    vault: _VaultLike | None,
    *,
    effect_context: CapabilityEffectContext,
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
    _register_self_repair(registry, config, effect_context)


def _self_repair_binding() -> Binding:
    return Binding(
        binding_id="builtin:self-repair:infra-action",
        workspace_id="default",
        project_id="default",
        node_id="self-repair",
        capability="infra_action",
    )


def _build_self_repair_effect_invoker(
    registry: CapabilityRegistry,
    effect_context: CapabilityEffectContext,
    binding: Binding,
) -> tuple[Callable[[], Any], Callable[[str, dict[str, Any], str], Any]]:
    async def resolve_action() -> InfraAction | None:
        provider = await registry.resolve("infra_action")
        return provider if isinstance(provider, InfraAction) else None

    async def invoke_action(action: str, params: dict[str, Any], effect_key: str) -> ActionResult:
        async def resolver(candidate: Binding) -> InfraAction | Unavailable:
            try:
                authorized = await effect_context.bindings.resolve(
                    candidate.binding_id,
                    workspace_id=binding.workspace_id,
                    project_id=binding.project_id,
                    node_id=binding.node_id,
                    capability=binding.capability,
                )
            except Exception:
                return Unavailable(slot="infra_action", reason="self_repair binding unavailable")
            if authorized.binding_id != binding.binding_id:
                return Unavailable(slot="infra_action", reason="invalid self_repair binding")
            provider = await resolve_action()
            return provider or Unavailable(slot="infra_action", reason="infra_action unavailable")

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            if not isinstance(provider, InfraAction):
                raise TypeError("infra_action Invocation resolved a non-action provider")
            payload = dict(request)
            result = await provider.act(str(payload["action"]), dict(payload.get("params") or {}))
            return {
                "ok": result.ok,
                "detail": result.detail,
                "blocked_pending_approval": result.blocked_pending_approval,
            }

        invocation = await effect_context.invocations.invoke(
            binding=binding,
            run_id="self-repair",
            node_run_id="self-repair",
            attempt_id=effect_key,
            effect_key=effect_key,
            request={"action": action, "params": params},
            resolver=resolver,
            executor=executor,
        )
        if not isinstance(invocation.result, dict):
            return ActionResult(ok=False, detail="infra_action Invocation returned no result")
        return ActionResult(
            ok=bool(invocation.result.get("ok")),
            detail=str(invocation.result.get("detail") or ""),
            blocked_pending_approval=bool(invocation.result.get("blocked_pending_approval")),
        )

    return resolve_action, invoke_action


def _register_self_repair(
    registry: CapabilityRegistry,
    config: Settings,
    effect_context: CapabilityEffectContext,
) -> None:
    """Register self_repair with decision-time infra_action admission (SPEC-188/#846)."""
    monitor = registry.provider("infra_monitor", "host_health")
    if monitor is None:
        return
    binding = _self_repair_binding()
    if not isinstance(effect_context.bindings, InMemoryBindingStore):
        logger.warning("self_repair disabled: BindingStore has no boot registration seam")
        return
    try:
        effect_context.bindings.register(binding)
    except Exception:
        logger.exception("self_repair disabled: failed to register its Binding")
        return
    resolve_action, invoke_action = _build_self_repair_effect_invoker(
        registry, effect_context, binding
    )
    registry.register(
        RuleBasedRepair(
            infra_monitor=monitor,
            infra_action_resolver=resolve_action,
            effect_invoker=invoke_action,
            autonomy=config.infra_autonomy,
        )
    )
    logger.info(
        "registered self_repair provider (Invocation-governed, autonomy=%s)",
        config.infra_autonomy,
    )


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
