"""Memory exposure mode — write-authority gating primitive (SPEC-249 / ADR-057)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Actor(StrEnum):
    SYSTEM = "system"
    AGENT = "agent"


class MemoryExposureMode(StrEnum):
    SYSTEM_MANAGED = "system_managed"
    AGENT_MANAGED = "agent_managed"
    HYBRID = "hybrid"


class BlockExposure(StrEnum):
    SYSTEM_MANAGED = "system_managed"
    AGENT_MANAGED = "agent_managed"


@dataclass(frozen=True)
class MemoryWriteDenied(Exception):
    scope: str
    actor: Actor
    mode: MemoryExposureMode
    reason: str


def _agent_allowed(mode: MemoryExposureMode, block_exposure: BlockExposure | None) -> bool:
    if mode == MemoryExposureMode.AGENT_MANAGED:
        return True
    if mode == MemoryExposureMode.SYSTEM_MANAGED:
        return False
    if block_exposure is None:
        raise ValueError("HYBRID mode requires block_exposure")
    return block_exposure == BlockExposure.AGENT_MANAGED


def _enforce(
    op: str,
    mode: MemoryExposureMode,
    actor: Actor,
    *,
    scope: str,
    block_exposure: BlockExposure | None,
) -> None:
    if actor == Actor.SYSTEM:
        return
    if _agent_allowed(mode, block_exposure):
        return
    raise MemoryWriteDenied(
        scope=scope,
        actor=actor,
        mode=mode,
        reason=f"agent {op} denied under {mode.value} exposure mode",
    )


def enforce_write(
    mode: MemoryExposureMode,
    actor: Actor,
    *,
    scope: str = "",
    block_exposure: BlockExposure | None = None,
) -> None:
    _enforce("write", mode, actor, scope=scope, block_exposure=block_exposure)


def enforce_promote(
    mode: MemoryExposureMode,
    actor: Actor,
    *,
    scope: str = "",
    block_exposure: BlockExposure | None = None,
) -> None:
    _enforce("promote", mode, actor, scope=scope, block_exposure=block_exposure)
