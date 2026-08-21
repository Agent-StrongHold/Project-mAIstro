"""App-side capability wiring: register host-health providers + apply activation (SPEC-187)."""

from __future__ import annotations

from config import Settings
from models.schemas import CapabilitySetting, SettingsModel
from pydantic import SecretStr
from services.capabilities_wiring import wire_capabilities

from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.slots.infra import InfraAction


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
