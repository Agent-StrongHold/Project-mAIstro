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
from maistro.capabilities.binding_store import register_boot_binding
from maistro.capabilities.durable_hitl_approval import admit_self_repair_approval
from maistro.capabilities.effect_context import CapabilityEffectContext, new_effect_context
from maistro.capabilities.http_client import HttpxAsyncHttp
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.providers.host_health import HostHealthAction, HostHealthMonitor
from maistro.capabilities.providers.self_repair import RuleBasedRepair
from maistro.capabilities.self_repair_incident import (
    chained_episode_token,
    episode_effect_key,
)
from maistro.capabilities.slots.infra import ActionResult, InfraAction
from maistro.capabilities.slots.self_repair import RepairProposal
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


async def wire_capabilities(
    registry: CapabilityRegistry,
    *,
    settings_model: SettingsModel,
    config: Settings,
    vault: _VaultLike | None = None,
    effect_context: CapabilityEffectContext | None = None,
) -> None:
    """Register host-health providers (if configured) then apply activation.

    Async because boot registration writes a Binding, and on a durable backend
    that write is I/O. The engine starts this from its own ``start()``, which
    is already a coroutine, so nothing gains a thread or a loop here.
    """
    await _register_host_health(
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


async def _register_host_health(
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
    registry.register(HostHealthMonitor(http))
    # #2405: HostHealthAction is a pure executor. Approval-gated self-repair
    # admits durable waiting-human NodeRuns; it must not await InboxApproval.
    registry.register(HostHealthAction(http, autonomy=config.infra_autonomy))
    logger.info("registered host-health infra providers -> %s", url)
    await _register_self_repair(registry, config, effect_context)


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
) -> Callable[[str, dict[str, Any], str], Any]:
    # A settled remediation must never be replayed for a later incident
    # (#2405 review): the Invocation ledger returns a COMPLETED row without a
    # provider call, and a repair that reported ``ok=False`` is still
    # COMPLETED — so the caller's permanent ``stable_effect_key`` would make
    # the second failure of the same operation silently inherit the first
    # result forever. Each settled generation therefore moves the identity,
    # deterministically, off durable facts. Same bound as the durable
    # approval path's episode chain (``MAX_EPISODE_CHAIN``).
    _MAX_EFFECT_GENERATIONS = 16

    async def _advance_past_settled(effect_key: str) -> str:
        """The caller's key until it names a settled effect; then its heir.

        Stable within an incident: nothing is settled under the key yet, so
        the ledger's in-flight guard still converges concurrent re-entry onto
        one physical effect. The heir chains from the settled row's
        invocation id, so a restart or a second replica walking the same
        canonical history derives the same next key. FAILED history stays
        under the same key — the ledger's own contract admits a fresh
        dispatch over a failed record; CREATED/RUNNING/UNKNOWN is refused by
        the ledger at admission, never replayed.
        """
        base_token = effect_key.rsplit(":", 1)[-1]
        key, token = effect_key, base_token
        for _ in range(_MAX_EFFECT_GENERATIONS):
            latest = await effect_context.invocations.latest_effect(
                binding=binding,
                run_id="self-repair",
                node_run_id="self-repair",
                effect_key=key,
            )
            if latest is None or latest.status is not InvocationStatus.COMPLETED:
                return key
            token = chained_episode_token(token, latest.invocation_id)
            key = episode_effect_key(effect_key, token, base_token=base_token)
        raise ValueError(
            f"self-repair effect {effect_key!r} has {_MAX_EFFECT_GENERATIONS} settled "
            "generations; refusing to derive a further incident identity"
        )

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
            provider = await registry.resolve("infra_action")
            if not isinstance(provider, InfraAction):
                return Unavailable(slot="infra_action", reason="infra_action unavailable")
            return provider

        async def executor(provider: Any, request: Any) -> dict[str, Any]:
            if not isinstance(provider, InfraAction):
                raise TypeError("infra_action Invocation resolved a non-action provider")
            payload = dict(request)
            # Auto-run path only (reversible under auto_safe). Gated tiers are
            # admitted as durable waiting-human Runs (#2405), not through here.
            result = await provider.act(str(payload["action"]), dict(payload.get("params") or {}))
            return {
                "ok": result.ok,
                "detail": result.detail,
                "blocked_pending_approval": result.blocked_pending_approval,
            }

        identity = await _advance_past_settled(effect_key)
        invocation = await effect_context.invocations.invoke(
            binding=binding,
            run_id="self-repair",
            node_run_id="self-repair",
            attempt_id=identity,
            effect_key=identity,
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

    return invoke_action


async def _resolve_self_repair_hitl_scope() -> tuple[str, str]:
    """Canonical Workspace + Root Project for self-repair approval Runs.

    The effect Binding keeps synthetic ids for ``infra_action`` resolution;
    HITL discovery (``/v1/hitl``) requires a real Project in
    ``authorized_project_ids``. Mirror the schedule admission rule: Hive's
    configured default Workspace and that Workspace's Root Project.
    """
    from config import get_settings

    from services.engine import get_engine

    engine = get_engine()
    container = getattr(getattr(engine, "_agent_port", None), "container", None)
    scope = getattr(container, "project_scope_store", None)
    if scope is None:
        raise RuntimeError("project_scope_store unavailable for durable self-repair approval")
    workspace_id = str(get_settings().hive_default_workspace_id or "").strip()
    if not workspace_id:
        raise RuntimeError("hive_default_workspace_id is unset for durable self-repair approval")
    root = await scope.root_for_workspace(workspace_id)
    return workspace_id, root.project_id


def _build_self_repair_approval_admittor(
    registry: CapabilityRegistry,
    effect_context: CapabilityEffectContext,
    binding: Binding,
) -> Callable[[RepairProposal, str], Any]:
    async def admit(proposal: RepairProposal, effect_key: str) -> str:
        from services.engine import get_engine

        engine = get_engine()
        store = engine.graph_run_store
        if store is None:
            raise RuntimeError("graph_run_store unavailable for durable self-repair approval")
        workspace_id, project_id = await _resolve_self_repair_hitl_scope()

        async def resolve_provider(candidate: Binding) -> InfraAction:
            try:
                authorized = await effect_context.bindings.resolve(
                    candidate.binding_id,
                    workspace_id=binding.workspace_id,
                    project_id=binding.project_id,
                    node_id=binding.node_id,
                    capability=binding.capability,
                )
            except Exception as exc:
                raise LookupError("self_repair binding unavailable") from exc
            if authorized.binding_id != binding.binding_id:
                raise LookupError("invalid self_repair binding")
            provider = await registry.resolve("infra_action")
            if not isinstance(provider, InfraAction):
                raise LookupError("infra_action unavailable")
            return provider

        record = await admit_self_repair_approval(
            store=store,
            effect_context=effect_context,
            binding=binding,
            workspace_id=workspace_id,
            project_id=project_id,
            action=proposal.action or "",
            params=proposal.params,
            effect_key=effect_key,
            resolve_provider=resolve_provider,
            run_store=engine.run_store,
            resource=proposal.resource,
        )
        return record.run.run_id

    return admit


def _build_self_repair_pending_hydration() -> Callable[[], Any]:
    """Durable index of pending self-repair approval waits (resource -> run_id).

    Restart hydration for ``RuleBasedRepair`` (#2405): a fresh process — or a
    second replica — must reconcile waits it did not admit itself before the
    next degraded snapshot, or the in-memory pending dict's emptiness would
    admit a second approval Run for one unresolved incident. The durable
    HITL-paused scan is the truth; this loader owns no state.
    """

    async def load_pending() -> dict[str, str]:
        from services.engine import get_engine

        store = get_engine().graph_run_store
        if store is None:
            # No durable HITL surface exists in this composition: durable
            # admission refuses up front (see the admittor), so no wait can
            # be parked anywhere. Empty is the truthful answer here — unlike
            # a store that exists but fails below, which stays fail-closed.
            return {}
        pending: dict[str, str] = {}
        after: tuple[str, str] | None = None
        while True:
            page = await store.list_hitl_paused(limit=100, after=after)
            for record in page.items:
                try:
                    graph = record.run.graph.materialize()
                except Exception:
                    continue
                if graph.metadata.get("admission_source") != "self_repair":
                    continue
                resource = record.run.provenance.get("self_repair_resource")
                if isinstance(resource, str) and resource:
                    pending[resource] = record.run.run_id
            if page.resume_after is None or page.exhausted:
                break
            after = page.resume_after
        return pending

    return load_pending


def _build_self_repair_approval_run_status() -> Callable[[str], Any]:
    async def status_of(run_id: str) -> str | None:
        from services.engine import get_engine

        store = get_engine().graph_run_store
        if store is None:
            return None
        record = await store.get(run_id)
        if record is None:
            return None
        return record.run.status.value

    return status_of


async def _register_self_repair(
    registry: CapabilityRegistry,
    config: Settings,
    effect_context: CapabilityEffectContext,
) -> None:
    """Register self_repair with decision-time infra_action admission (SPEC-188/#846).

    Boot registration goes through ``register_boot_binding``, which every
    backend supports -- in-memory, SQLite and PostgreSQL alike. It previously went
    through the in-memory store's synchronous ``register``, so this narrowed to
    that concrete class first and self_repair turned itself off on exactly the
    deployments that persist anything (#1133). ``put`` has the semantics boot
    registration needs on all three: idempotent for an identical Binding,
    `ValueError` for a changed one, and `BindingNotFound` for an identity that
    has been revoked -- which on a durable store means revoked in some earlier
    process, by a tombstone that outlived it.

    Approval-gated remediations admit durable waiting-human NodeRuns (#2405)
    rather than awaiting ``InboxApproval``'s in-process Event.
    """
    monitor = registry.provider("infra_monitor", "host_health")
    if monitor is None:
        return
    try:
        binding = await register_boot_binding(effect_context.bindings, _self_repair_binding())
    except Exception:
        logger.exception("self_repair disabled: failed to register its Binding")
        return
    invoke_action = _build_self_repair_effect_invoker(registry, effect_context, binding)
    admit_approval = _build_self_repair_approval_admittor(registry, effect_context, binding)
    registry.register(
        RuleBasedRepair(
            infra_monitor=monitor,
            effect_invoker=invoke_action,
            approval_admittor=admit_approval,
            approval_run_status=_build_self_repair_approval_run_status(),
            pending_approvals_loader=_build_self_repair_pending_hydration(),
            autonomy=config.infra_autonomy,
        )
    )
    logger.info(
        "registered self_repair provider (Invocation-governed, durable HITL, autonomy=%s)",
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
