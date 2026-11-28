"""App-side capability wiring: register host-health providers + apply activation (SPEC-187)."""

from __future__ import annotations

import pytest
from config import Settings
from models.schemas import CapabilitySetting, SettingsModel
from pydantic import SecretStr
from services.capabilities_wiring import _register_self_repair, wire_capabilities

from maistro.capabilities.binding_store import register_boot_binding
from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
from maistro.capabilities.slots.infra import (
    ActionResult,
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


async def test_registers_host_health_providers_when_url_present() -> None:
    reg = default_capability_registry()
    await wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150", host_health_token=SecretStr("t")),
        vault=None,
    )
    assert "host_health" in reg.installed("infra_monitor")
    assert "host_health" in reg.installed("infra_action")


async def test_no_url_leaves_infra_slots_empty() -> None:
    reg = default_capability_registry()
    await wire_capabilities(
        reg, settings_model=SettingsModel(), config=_cfg(host_health_url=None), vault=None
    )
    assert reg.installed("infra_monitor") == []
    assert reg.installed("infra_action") == []


async def test_action_does_not_wire_in_process_inbox_approval() -> None:
    """#2405: HostHealthAction is a pure executor; no InboxApproval Event wait."""
    from maistro.capabilities.providers.host_health import HostHealthAction
    from maistro.capabilities.providers.self_repair import RuleBasedRepair

    reg = default_capability_registry()
    await wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150"),
        vault=None,
    )
    action = reg.provider("infra_action", "host_health")
    assert isinstance(action, HostHealthAction)
    assert not hasattr(action, "_approval")
    repair = reg.provider("self_repair", "rule_based_repair")
    assert isinstance(repair, RuleBasedRepair)
    assert repair._approval_admittor is not None


async def test_token_prefers_vault_over_env_fallback() -> None:
    reg = default_capability_registry()
    vault = _FakeVault({"HOST_HEALTH_TOKEN": "from-vault"})
    await wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150", host_health_token=SecretStr("from-env")),
        vault=vault,
    )
    action = reg.provider("infra_action", "host_health")
    # token lives behind the http seam; assert via the seam's auth header.
    assert action._http._headers.get("Authorization") == "Bearer from-vault"


async def test_token_env_fallback_when_vault_missing_secret() -> None:
    reg = default_capability_registry()
    vault = _FakeVault({})  # no HOST_HEALTH_TOKEN
    await wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150", host_health_token=SecretStr("from-env")),
        vault=vault,
    )
    action = reg.provider("infra_action", "host_health")
    assert action._http._headers.get("Authorization") == "Bearer from-env"


async def test_applies_activation_from_settings() -> None:
    reg = default_capability_registry()
    settings_model = SettingsModel(
        capabilities={
            "approval": CapabilitySetting(enabled=True, active_provider="inbox"),
            "infra_action": CapabilitySetting(enabled=False),
        }
    )
    await wire_capabilities(
        reg,
        settings_model=settings_model,
        config=_cfg(host_health_url="http://host:8150"),
        vault=None,
    )
    assert reg.active_name("approval") == "inbox"
    assert reg.is_enabled("infra_action") is False


async def test_activation_ignores_unknown_slot() -> None:
    reg = default_capability_registry()
    settings_model = SettingsModel(capabilities={"no_such_slot": CapabilitySetting()})
    # Must not raise — bad settings shouldn't crash startup.
    await wire_capabilities(reg, settings_model=settings_model, config=_cfg(), vault=None)


async def test_registers_self_repair_when_infra_present() -> None:
    reg = default_capability_registry()
    await wire_capabilities(
        reg,
        settings_model=SettingsModel(),
        config=_cfg(host_health_url="http://host:8150"),
        vault=None,
    )
    assert "rule_based_repair" in reg.installed("self_repair")


async def test_no_self_repair_without_infra() -> None:
    reg = default_capability_registry()
    await wire_capabilities(
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
    await _register_self_repair(reg, _cfg(), effects)
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

    await _register_self_repair(reg, _cfg(), effects)
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


async def test_engine_exposes_a_capability_registry_in_stub_mode() -> None:
    # The API reaches capabilities via the engine; it must exist even with no
    # real maistro-core container wired (stub/dev mode).
    from services.engine import EngineService

    svc = EngineService()
    svc._agent_port = object()  # not a bridge → no .container
    await svc._wire_capabilities(_cfg(host_health_url="http://host:8150"))
    assert "inbox" in svc.capabilities.installed("approval")
    assert "host_health" in svc.capabilities.installed("infra_action")


# --- #846: self_repair registration must fail closed on a hostile composition


class _UnwritableStore:
    """A BindingStore whose boot write fails, however it is called."""

    async def resolve(self, binding_id, *, workspace_id, project_id, node_id, capability):
        raise NotImplementedError

    async def put(self, binding):
        raise RuntimeError("binding store is unavailable")

    async def get(self, binding_id):
        return None

    async def revoke(self, binding_id):
        raise NotImplementedError


async def test_no_self_repair_registered_without_monitor_provider() -> None:
    # A monitor provider is a hard precondition: without it the actor would
    # hold an invoker with nothing to observe, so nothing is registered.
    reg = default_capability_registry(entry_points=[])
    effects = new_effect_context(policy_evaluator=binding_scope_policy)

    await _register_self_repair(reg, _cfg(), effects)

    assert reg.installed("self_repair") == []
    assert reg.provider("self_repair", "rule_based_repair") is None


async def test_self_repair_disabled_when_the_boot_write_fails() -> None:
    """A Binding that could not be written authorizes nothing, so nothing runs.

    Registering the actor anyway would leave it holding an invoker whose
    identity the store has never heard of -- every repair it attempted would
    be refused at resolve time, after the actor had already decided to act.
    """

    import dataclasses

    reg = default_capability_registry(entry_points=[])
    reg.register(_WiringMonitor())
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    degraded = dataclasses.replace(effects, bindings=_UnwritableStore())

    await _register_self_repair(reg, _cfg(), degraded)

    assert reg.installed("self_repair") == []
    assert reg.provider("self_repair", "rule_based_repair") is None


async def test_self_repair_registers_against_a_durable_binding_store() -> None:
    """The point of #1133: persistence must not switch self_repair off.

    Boot registration used to go through the in-memory store's synchronous
    `register`, so the wiring narrowed to that concrete class and skipped
    registration entirely on SQLite or PostgreSQL -- exactly the deployments
    that keep anything across a restart. `put` is on every backend, so the
    durable store registers the identity and the actor comes up.
    """

    import dataclasses

    import aiosqlite

    from maistro.capabilities.binding_store import SqliteBindingStore

    async with aiosqlite.connect(":memory:") as conn:
        durable = SqliteBindingStore(conn)
        await durable.ensure_schema()
        reg = default_capability_registry(entry_points=[])
        reg.register(_WiringMonitor())
        effects = new_effect_context(policy_evaluator=binding_scope_policy)
        persisted = dataclasses.replace(effects, bindings=durable)

        await _register_self_repair(reg, _cfg(), persisted)

        assert reg.provider("self_repair", "rule_based_repair") is not None
        # Registered in the durable store itself, not merely in the registry:
        # the invoker resolves this identity on every repair it attempts.
        assert await durable.get("builtin:self-repair:infra-action") is not None


async def test_self_repair_survives_a_restart_against_the_same_database() -> None:
    """The second boot must behave like the first, or persistence breaks it.

    A durable store compares the whole Binding, and each process builds its
    boot Binding with a fresh `created_at`. Registering with a plain `put`
    therefore worked once and raised `ValueError` on every restart after,
    which left `self_repair` disabled on exactly the deployments that keep
    anything -- the opposite of what #1759 set out to fix (Codex, #1760).
    """

    import dataclasses

    import aiosqlite

    from maistro.capabilities.binding_store import SqliteBindingStore

    async with aiosqlite.connect(":memory:") as conn:
        durable = SqliteBindingStore(conn)
        await durable.ensure_schema()

        for boot in (1, 2):
            # A fresh registry each time: a new process, same database.
            reg = default_capability_registry(entry_points=[])
            reg.register(_WiringMonitor())
            effects = new_effect_context(policy_evaluator=binding_scope_policy)
            persisted = dataclasses.replace(effects, bindings=durable)

            await _register_self_repair(reg, _cfg(), persisted)

            assert reg.provider("self_repair", "rule_based_repair") is not None, (
                f"self_repair did not register on boot {boot}"
            )


async def test_a_revocation_that_outlived_a_restart_still_disables_self_repair() -> None:
    """Revocation is durable, so boot must not re-grant across a restart.

    The tombstone in `capability_binding_revocations` is the whole reason that
    table exists apart from `capability_bindings` (#846). A new process that
    re-registered the identity would quietly undo an operator's revocation --
    the failure mode that made boot registration worth gating in the first
    place, and the one that must survive opening the seam.
    """

    import dataclasses

    import aiosqlite

    from maistro.capabilities.binding_store import SqliteBindingStore

    async with aiosqlite.connect(":memory:") as conn:
        durable = SqliteBindingStore(conn)
        await durable.ensure_schema()
        await durable.revoke("builtin:self-repair:infra-action")

        # A fresh process: same database, new registry, boot wiring runs again.
        reg = default_capability_registry(entry_points=[])
        reg.register(_WiringMonitor())
        effects = new_effect_context(policy_evaluator=binding_scope_policy)
        persisted = dataclasses.replace(effects, bindings=durable)

        await _register_self_repair(reg, _cfg(), persisted)

        assert reg.installed("self_repair") == []
        assert await durable.get("builtin:self-repair:infra-action") is None


async def test_self_repair_disabled_when_boot_binding_was_revoked() -> None:
    reg = default_capability_registry(entry_points=[])
    reg.register(_WiringMonitor())
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.revoke("builtin:self-repair:infra-action")

    await _register_self_repair(reg, _cfg(), effects)

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


async def test_self_repair_invoker_advances_effect_identity_after_settlement() -> None:
    """A settled remediation is never replayed for a later incident (#2405).

    The Invocation ledger returns a COMPLETED row without a provider call, and
    a repair that reported ``ok=False`` is still COMPLETED — the reviewer's
    P1: a second failure of the same resource under the caller's permanent
    key would silently inherit the first result forever. The invoker must
    keep the key stable within an incident (nothing settled yet) and derive
    the next generation deterministically once it settles, so later
    incidents — including retries after an ``ok=False`` result — dispatch.
    """

    class _ResultSwitchingAction(_WiringAction):
        """Same operation every time; the outcome is the test's lever."""

        def __init__(self) -> None:
            super().__init__()
            self.ok = False

        async def act(self, action: str, params: dict) -> ActionResult:
            self.calls.append((action, params))
            return ActionResult(ok=self.ok, detail="done")

    from services.capabilities_wiring import (
        _build_self_repair_effect_invoker,
        _self_repair_binding,
    )

    reg = default_capability_registry(entry_points=[])
    action = _ResultSwitchingAction()
    reg.register(_WiringMonitor())
    reg.register(action)
    reg.activate("infra_monitor", "host_health")
    reg.activate("infra_action", "host_health")

    binding = _self_repair_binding()
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    await register_boot_binding(effects.bindings, binding)
    invoke_action = _build_self_repair_effect_invoker(reg, effects, binding)
    key = "self_repair:litellm:restart_container:640d0bd823a04f4e"

    # Incident 1 settles COMPLETED with ok=False (a normal provider result,
    # not a ledger FAILED) — a later incident must still dispatch.
    first = await invoke_action("restart_container", {"name": "litellm"}, key)
    assert first.ok is False
    assert len(action.calls) == 1

    second = await invoke_action("restart_container", {"name": "litellm"}, key)
    assert len(action.calls) == 2, "settled ok=False generation was replayed"

    action.ok = True
    third = await invoke_action("restart_container", {"name": "litellm"}, key)
    assert third.ok is True
    assert len(action.calls) == 3, "the second settled generation was replayed"

    records = list(effects.invocation_store._items.values())
    assert len(records) == 3
    assert len({record.effect_key for record in records}) == 3, (
        "each settled incident must carry a distinct effect identity"
    )
    assert all(record.effect_key.startswith("self_repair:litellm:restart_container:") for record in records)


# --- #2405: durable HITL scope + approval admittor / run-status seams


async def _async_pair(a: str, b: str):
    return a, b


def _proposal(**kw):
    from maistro.capabilities.slots.self_repair import RepairProposal

    base = {
        "resource": "docker:litellm",
        "symptom": "unhealthy",
        "action": "restart_container",
        "params": {"name": "litellm"},
    }
    base.update(kw)
    return RepairProposal(**base)


async def test_resolve_self_repair_hitl_scope_uses_hive_default_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from services.capabilities_wiring import _resolve_self_repair_hitl_scope

    from maistro.projects.scope_store import InMemoryProjectScopeStore

    scope = InMemoryProjectScopeStore()
    root = await scope.create_root("ws-hive-2405")
    monkeypatch.setattr(
        "config.get_settings",
        lambda: SimpleNamespace(hive_default_workspace_id="ws-hive-2405"),
    )
    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(
            _agent_port=SimpleNamespace(
                container=SimpleNamespace(project_scope_store=scope),
            ),
        ),
    )

    workspace_id, project_id = await _resolve_self_repair_hitl_scope()
    assert workspace_id == "ws-hive-2405"
    assert project_id == root.project_id


async def test_resolve_self_repair_hitl_scope_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from services.capabilities_wiring import _resolve_self_repair_hitl_scope

    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(_agent_port=SimpleNamespace(container=None)),
    )
    with pytest.raises(RuntimeError, match="project_scope_store unavailable"):
        await _resolve_self_repair_hitl_scope()

    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(
            _agent_port=SimpleNamespace(
                container=SimpleNamespace(project_scope_store=object()),
            ),
        ),
    )
    monkeypatch.setattr(
        "config.get_settings",
        lambda: SimpleNamespace(hive_default_workspace_id=""),
    )
    with pytest.raises(RuntimeError, match="hive_default_workspace_id is unset"):
        await _resolve_self_repair_hitl_scope()


async def test_self_repair_approval_run_status_reads_graph_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from services.capabilities_wiring import _build_self_repair_approval_run_status

    from maistro.graph.durable_runs import RunStatus

    class _Store:
        def __init__(self) -> None:
            self.by_id = {
                "run-paused": SimpleNamespace(
                    run=SimpleNamespace(status=RunStatus.PAUSED),
                ),
            }

        async def get(self, run_id: str):
            return self.by_id.get(run_id)

    status_of = _build_self_repair_approval_run_status()
    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(graph_run_store=None),
    )
    assert await status_of("anything") is None

    store = _Store()
    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(graph_run_store=store),
    )
    assert await status_of("missing") is None
    assert await status_of("run-paused") == RunStatus.PAUSED.value


async def test_self_repair_approval_admittor_requires_graph_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from services.capabilities_wiring import (
        _build_self_repair_approval_admittor,
        _self_repair_binding,
    )

    reg = default_capability_registry(entry_points=[])
    binding = _self_repair_binding()
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(graph_run_store=None, run_store=None),
    )
    admit = _build_self_repair_approval_admittor(reg, effects, binding)
    with pytest.raises(RuntimeError, match="graph_run_store unavailable"):
        await admit(_proposal(), "ek")


async def test_self_repair_approval_admittor_parks_and_resolves_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admittor resolves Hive scope, parks via admit, and resolve_provider admits."""
    import dataclasses
    from types import SimpleNamespace

    from services.capabilities_wiring import (
        _build_self_repair_approval_admittor,
        _self_repair_binding,
    )

    from maistro.capabilities.binding_store import InMemoryBindingStore
    from maistro.graph.durable_runs import RunStatus

    reg = default_capability_registry(entry_points=[])
    action = _WiringAction()
    reg.register(_WiringMonitor())
    reg.register(action)
    reg.activate("infra_action", "host_health")

    binding = _self_repair_binding()
    store = InMemoryBindingStore()
    store.register(binding)
    effects = dataclasses.replace(
        new_effect_context(policy_evaluator=binding_scope_policy), bindings=store
    )

    monkeypatch.setattr(
        "services.capabilities_wiring._resolve_self_repair_hitl_scope",
        lambda: _async_pair("ws-admit", "project-admit"),
    )
    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(graph_run_store=object(), run_store=object()),
    )

    admitted: list[dict[str, object]] = []

    async def fake_admit(**kwargs):
        admitted.append(kwargs)
        provider = await kwargs["resolve_provider"](binding)
        assert provider is action
        return SimpleNamespace(run=SimpleNamespace(run_id="run-admit-1", status=RunStatus.PAUSED))

    monkeypatch.setattr(
        "services.capabilities_wiring.admit_self_repair_approval",
        fake_admit,
    )

    admit = _build_self_repair_approval_admittor(reg, effects, binding)
    run_id = await admit(_proposal(), "self_repair:docker:restart_container:1")
    assert run_id == "run-admit-1"
    assert admitted[0]["workspace_id"] == "ws-admit"
    assert admitted[0]["project_id"] == "project-admit"
    assert admitted[0]["effect_key"] == "self_repair:docker:restart_container:1"
    assert admitted[0]["run_store"] is not None


async def test_self_repair_approval_admittor_resolve_provider_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Binding resolve failures / redirects / missing infra refuse closed."""
    import dataclasses
    from types import SimpleNamespace

    from services.capabilities_wiring import (
        _build_self_repair_approval_admittor,
        _self_repair_binding,
    )

    from maistro.capabilities.binding_store import InMemoryBindingStore
    from maistro.graph.durable_runs import RunStatus

    binding = _self_repair_binding()

    class _RedirectingStore(InMemoryBindingStore):
        async def resolve(self, binding_id, **kwargs):
            resolved = await super().resolve(binding_id, **kwargs)
            return resolved.model_copy(update={"binding_id": "builtin:redirected"})

    async def boom(*_a, **_k):
        raise RuntimeError("bindings down")

    monkeypatch.setattr(
        "services.capabilities_wiring._resolve_self_repair_hitl_scope",
        lambda: _async_pair("ws", "proj"),
    )
    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(graph_run_store=object(), run_store=None),
    )

    async def exercise(effects, registry, match: str) -> None:
        seen: list[object] = []

        async def fake_admit(**kwargs):
            with pytest.raises(LookupError, match=match):
                await kwargs["resolve_provider"](binding)
            seen.append(True)
            return SimpleNamespace(run=SimpleNamespace(run_id="run-x", status=RunStatus.PAUSED))

        monkeypatch.setattr(
            "services.capabilities_wiring.admit_self_repair_approval",
            fake_admit,
        )
        admit = _build_self_repair_approval_admittor(registry, effects, binding)
        assert await admit(_proposal(), "ek") == "run-x"
        assert seen

    # Exception from BindingStore.resolve → LookupError
    hostile = dataclasses.replace(
        new_effect_context(policy_evaluator=binding_scope_policy),
        bindings=SimpleNamespace(resolve=boom),
    )
    await exercise(hostile, default_capability_registry(entry_points=[]), "binding unavailable")

    # Redirected identity → invalid self_repair binding
    redirecting = _RedirectingStore()
    redirecting.register(binding)
    redirected = dataclasses.replace(
        new_effect_context(policy_evaluator=binding_scope_policy),
        bindings=redirecting,
    )
    await exercise(
        redirected, default_capability_registry(entry_points=[]), "invalid self_repair binding"
    )

    # Binding ok but no infra_action provider → infra_action unavailable
    ok_store = InMemoryBindingStore()
    ok_store.register(binding)
    ok_effects = dataclasses.replace(
        new_effect_context(policy_evaluator=binding_scope_policy), bindings=ok_store
    )
    bare = default_capability_registry(entry_points=[])
    await exercise(ok_effects, bare, "infra_action unavailable")
