"""App-side capability wiring: register host-health providers + apply activation (SPEC-187)."""

from __future__ import annotations

import pytest
from config import Settings
from models.schemas import CapabilitySetting, SettingsModel
from pydantic import SecretStr
from services.capabilities_wiring import _register_self_repair, wire_capabilities

from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
from maistro.capabilities.slots.infra import (
    ActionResult,
    InfraAction,
    InfraHealth,
    ResourceHealth,
)
from maistro.capabilities.types import ProviderHealth


class _FakeVault:
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def use(self, name: str, callback):
        if name not in self._secrets:
            raise KeyError(name)
        return callback(self._secrets[name])


def _cfg(**kw) -> Settings:
    return Settings(**kw)


def test_registers_host_health_providers_when_url_present() -> None:
    reg = default_capability_registry()
    wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150", host_health_token=SecretStr("t")),
        vault=None,
    )
    assert "host_health" in reg.installed("infra_monitor")
    assert "host_health" in reg.installed("infra_action")


def test_no_url_leaves_infra_slots_empty() -> None:
    reg = default_capability_registry()
    wire_capabilities(
        reg, settings_model=SettingsModel(), config=_cfg(host_health_url=None), vault=None
    )
    assert reg.installed("infra_monitor") == []
    assert reg.installed("infra_action") == []


def test_action_shares_the_registry_inbox_instance() -> None:
    reg = default_capability_registry()
    wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150"),
        vault=None,
    )
    action = reg.provider("infra_action", "host_health")
    assert isinstance(action, InfraAction)
    # The action's approval provider must be the same inbox the routes resolve.
    inbox = reg.provider("approval", "inbox")
    assert action._approval is inbox  # asserting shared wiring


def test_token_prefers_vault_over_env_fallback() -> None:
    reg = default_capability_registry()
    vault = _FakeVault({"HOST_HEALTH_TOKEN": "from-vault"})
    wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150", host_health_token=SecretStr("from-env")),
        vault=vault,
    )
    action = reg.provider("infra_action", "host_health")
    # token lives behind the http seam; assert via the seam's auth header.
    assert action._http._headers.get("Authorization") == "Bearer from-vault"


def test_token_env_fallback_when_vault_missing_secret() -> None:
    reg = default_capability_registry()
    vault = _FakeVault({})  # no HOST_HEALTH_TOKEN
    wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150", host_health_token=SecretStr("from-env")),
        vault=vault,
    )
    action = reg.provider("infra_action", "host_health")
    assert action._http._headers.get("Authorization") == "Bearer from-env"


def test_applies_activation_from_settings() -> None:
    reg = default_capability_registry()
    settings_model = SettingsModel(
        capabilities={
            "approval": CapabilitySetting(enabled=True, active_provider="inbox"),
            "infra_action": CapabilitySetting(enabled=False),
        }
    )
    wire_capabilities(
        reg,
        settings_model=settings_model,
        config=_cfg(host_health_url="http://host:8150"),
        vault=None,
    )
    assert reg.active_name("approval") == "inbox"
    assert reg.is_enabled("infra_action") is False


def test_activation_ignores_unknown_slot() -> None:
    reg = default_capability_registry()
    settings_model = SettingsModel(capabilities={"no_such_slot": CapabilitySetting()})
    # Must not raise — bad settings shouldn't crash startup.
    wire_capabilities(reg, settings_model=settings_model, config=_cfg(), vault=None)


def test_registers_self_repair_when_infra_present() -> None:
    reg = default_capability_registry()
    wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150"),
        vault=None,
    )
    assert "rule_based_repair" in reg.installed("self_repair")


def test_no_self_repair_without_infra() -> None:
    reg = default_capability_registry()
    wire_capabilities(
        reg, settings_model=SettingsModel(), config=_cfg(host_health_url=None), vault=None
    )
    assert reg.installed("self_repair") == []


class _WiringMonitor:
    name = "host_health"
    slot = "infra_monitor"
    trust_tier = "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    async def snapshot(self) -> InfraHealth:
        return InfraHealth(
            ts="t",
            resources={
                "docker": ResourceHealth(
                    "degraded", {"containers": [{"name": "litellm", "state": "unhealthy"}]}
                )
            },
        )


class _WiringAction:
    name = "host_health"
    slot = "infra_action"
    trust_tier = "t0"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    def allowed_actions(self) -> tuple[str, ...]:
        return ("restart_container",)

    async def act(self, action: str, params: dict) -> ActionResult:
        self.calls.append((action, params))
        return ActionResult(ok=True, detail="done")


async def test_self_repair_policy_failure_denies_without_provider_call() -> None:
    reg = default_capability_registry(entry_points=[])
    action = _WiringAction()
    reg.register(_WiringMonitor())
    reg.register(action)

    async def broken_policy(*_args, **_kwargs):
        raise RuntimeError("policy store unavailable")

    effects = new_effect_context(policy_evaluator=broken_policy)
    _register_self_repair(reg, _cfg(), effects)
    repair = reg.provider("self_repair", "rule_based_repair")
    assert repair is not None

    cycle = await repair.run_once()

    assert cycle.results[0].decision.value == "failed"
    assert action.calls == []
    assert "capability invocation policy unavailable" in cycle.results[0].detail
    events = await effects.event_store.list_stream("workspace:default")
    assert any(
        event.type == "capability.invocation.policy_decision"
        and event.payload["decision"] == "deny"
        for event in events
    )


async def test_self_repair_wiring_uses_canonical_invocation() -> None:
    reg = default_capability_registry(entry_points=[])
    action = _WiringAction()
    reg.register(_WiringMonitor())
    reg.register(action)
    effects = new_effect_context(policy_evaluator=binding_scope_policy)

    _register_self_repair(reg, _cfg(), effects)
    repair = reg.provider("self_repair", "rule_based_repair")
    assert repair is not None
    cycle = await repair.run_once()

    assert cycle.acted and action.calls == [("restart_container", {"name": "litellm"})]
    records = list(effects.invocation_store._items.values())
    assert len(records) == 1
    assert records[0].status.value == "completed"
    assert records[0].binding.binding_id == "builtin:self-repair:infra-action"


class _FakeSelfRepair:
    name = "rule_based_repair"
    slot = "self_repair"
    trust_tier = "t0"

    def __init__(self) -> None:
        self.runs = 0

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self):
        from maistro.capabilities.types import ProviderHealth

        return ProviderHealth(healthy=True)

    async def run_once(self):
        from maistro.capabilities.slots.self_repair import RepairCycleResult

        self.runs += 1
        return RepairCycleResult(ts="t", results=[])


async def test_run_self_repair_once_runs_when_enabled() -> None:
    from services.capabilities_wiring import run_self_repair_once

    reg = default_capability_registry()
    reg.register(_FakeSelfRepair())
    cycle = await run_self_repair_once(reg)
    assert cycle is not None  # provider resolved + ran


async def test_run_self_repair_once_killswitch_when_slot_disabled() -> None:
    from services.capabilities_wiring import run_self_repair_once

    reg = default_capability_registry()
    reg.register(_FakeSelfRepair())
    reg.set_enabled("self_repair", False)  # kill-switch → resolve None → no run
    assert await run_self_repair_once(reg) is None


def test_engine_exposes_a_capability_registry_in_stub_mode() -> None:
    # The API reaches capabilities via the engine; it must exist even with no
    # real maistro-core container wired (stub/dev mode).
    from services.engine import EngineService

    svc = EngineService()
    svc._agent_port = object()  # not a bridge → no .container
    svc._wire_capabilities(_cfg(host_health_url="http://host:8150"))
    assert "inbox" in svc.capabilities.installed("approval")
    assert "host_health" in svc.capabilities.installed("infra_action")


# --- #846: self_repair registration must fail closed on a hostile composition


class _NoBootSeamStore:
    """A BindingStore without the composition-time registration seam."""

    async def resolve(self, binding_id, *, workspace_id, project_id, node_id, capability):
        raise NotImplementedError

    def register(self, binding):
        raise NotImplementedError

    async def revoke(self, binding_id):
        raise NotImplementedError


def test_no_self_repair_registered_without_monitor_provider() -> None:
    # A monitor provider is a hard precondition: without it the actor would
    # hold an invoker with nothing to observe, so nothing is registered.
    reg = default_capability_registry(entry_points=[])
    effects = new_effect_context(policy_evaluator=binding_scope_policy)

    _register_self_repair(reg, _cfg(), effects)

    assert reg.installed("self_repair") == []
    assert reg.provider("self_repair", "rule_based_repair") is None


def test_self_repair_disabled_when_binding_store_lacks_boot_seam() -> None:
    import dataclasses

    reg = default_capability_registry(entry_points=[])
    reg.register(_WiringMonitor())
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    degraded = dataclasses.replace(effects, bindings=_NoBootSeamStore())

    _register_self_repair(reg, _cfg(), degraded)

    assert reg.installed("self_repair") == []
    assert reg.provider("self_repair", "rule_based_repair") is None


async def test_self_repair_disabled_when_boot_binding_was_revoked() -> None:
    reg = default_capability_registry(entry_points=[])
    reg.register(_WiringMonitor())
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.revoke("builtin:self-repair:infra-action")

    _register_self_repair(reg, _cfg(), effects)

    # A revoked identity is never re-granted by boot wiring: the actor that
    # would have held the invoker is not registered at all.
    assert reg.installed("self_repair") == []
    assert reg.provider("self_repair", "rule_based_repair") is None


async def test_self_repair_invoker_refuses_a_redirected_binding() -> None:
    """The invoker admits only the boot-registered identity (#846).

    If a BindingStore resolves an identity other than the one the composition
    root registered, the guarded invoker must refuse before any provider work —
    a redirected or swapped Binding can never borrow self_repair's admission.
    """
    import dataclasses

    from services.capabilities_wiring import (
        _build_self_repair_effect_invoker,
        _self_repair_binding,
    )

    from maistro.capabilities.binding_store import InMemoryBindingStore
    from maistro.capabilities.invocation import CapabilityUnavailable

    reg = default_capability_registry(entry_points=[])
    action = _WiringAction()
    reg.register(_WiringMonitor())
    reg.register(action)
    reg.activate("infra_monitor", "host_health")
    reg.activate("infra_action", "host_health")

    binding = _self_repair_binding()

    class _RedirectingStore(InMemoryBindingStore):
        """A hostile store that resolves a different identity than requested."""

        async def resolve(self, binding_id, **kwargs):
            resolved = await super().resolve(binding_id, **kwargs)
            return resolved.model_copy(update={"binding_id": "builtin:redirected"})

    store = _RedirectingStore()
    store.register(binding)
    effects = dataclasses.replace(
        new_effect_context(policy_evaluator=binding_scope_policy), bindings=store
    )

    invoke_action = _build_self_repair_effect_invoker(reg, effects, binding)
    with pytest.raises(CapabilityUnavailable, match="invalid self_repair binding"):
        await invoke_action("restart_container", {"name": "litellm"}, "effect-k")

    assert action.calls == []  # refused before any provider call
