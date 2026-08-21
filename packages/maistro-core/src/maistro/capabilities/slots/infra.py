"""infra_monitor + infra_action slot types and protocols (SPEC-187)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from maistro.capabilities.protocols import CapabilityProvider


class ActionTier(StrEnum):
    READ = "read"
    REVERSIBLE = "reversible"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ResourceHealth:
    status: str  # "ok" | "degraded" | "down"
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InfraHealth:
    ts: str
    resources: dict[str, ResourceHealth] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    detail: str = ""
    blocked_pending_approval: bool = False


@runtime_checkable
class InfraMonitor(CapabilityProvider, Protocol):
    async def snapshot(self) -> InfraHealth: ...


@runtime_checkable
class InfraAction(CapabilityProvider, Protocol):
    def allowed_actions(self) -> tuple[str, ...]: ...
    async def act(self, action: str, params: dict[str, Any]) -> ActionResult: ...


_READ_ACTIONS = {"docker_logs", "ollama_list", "snapraid_status"}
_REVERSIBLE_ACTIONS = {"restart_container", "restart_service", "ollama_pull"}
_DESTRUCTIVE_ACTIONS = {"restart_stack", "docker_prune"}
_VM_READ = {"status"}
_VM_REVERSIBLE = {"start"}
_VM_DESTRUCTIVE = {"stop", "reboot"}


def tier_for(action: str, params: dict[str, Any]) -> ActionTier:
    """Classify a host action by blast radius. Unknown -> DESTRUCTIVE (fail safe)."""
    if action in _READ_ACTIONS:
        return ActionTier.READ
    if action in _REVERSIBLE_ACTIONS:
        return ActionTier.REVERSIBLE
    if action in _DESTRUCTIVE_ACTIONS:
        return ActionTier.DESTRUCTIVE
    if action == "vm_control":
        vm_action = str(params.get("action", ""))
        if vm_action in _VM_READ:
            return ActionTier.READ
        if vm_action in _VM_REVERSIBLE:
            return ActionTier.REVERSIBLE
        if vm_action in _VM_DESTRUCTIVE:
            return ActionTier.DESTRUCTIVE
    return ActionTier.DESTRUCTIVE
