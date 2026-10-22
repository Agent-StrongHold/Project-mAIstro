"""Memory exposure mode — write-authority gating primitive (SPEC-249 / ADR-057).

SPEC-062126-6a31 wires this module into the real memory stores: every mutating
store entry calls :func:`require_write_authority` **before** it touches state, so
a store that was constructed without a declared :class:`MemoryExposureMode`
refuses every mutation (fail-closed — there is no implicit default), and an
agent-actor write under ``SYSTEM_MANAGED`` raises :class:`MemoryWriteDenied`.
"""

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


class MemoryUndeclaredModeError(Exception):
    """A memory store with no declared exposure mode was asked to mutate.

    SPEC-062126-6a31: there is no implicit default. A store that cannot say who
    holds write authority refuses to mutate at all — failing closed is the point,
    so the error is raised before any state changes. The SPEC sketched the
    parameter as ``agent_id``; the enforcement point that actually shipped is the
    store boundary, so the parameter names the undeclared *subject* (an agent id
    where one exists, the store class name where the store is shared).
    """

    def __init__(self, subject: str) -> None:
        self.subject = subject
        super().__init__(
            f"Memory store '{subject}' has no declared memory exposure_mode; "
            "declare one explicitly (AgentConfig.memory.exposure_mode) before it can mutate."
        )


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


def require_write_authority(
    mode: MemoryExposureMode | None,
    op: str,
    actor: Actor,
    *,
    subject: str,
    block_exposure: BlockExposure | None = None,
) -> None:
    """The one gate every memory mutation must pass, at the store boundary.

    Called as the first statement of a mutating store method, before provenance,
    dedup probes, SQL, or list appends: a denied or undeclared call raises here
    and the store's durable state is untouched — denied writes leave no partial
    state. ``mode is None`` fails closed with
    :class:`MemoryUndeclaredModeError`; otherwise the ADR-057 matrix decides.

    The decision reads only the declared mode, the actor, and the per-block tag —
    never the block's content — so authorization cannot be steered by model or
    persona output.
    """
    if mode is None:
        raise MemoryUndeclaredModeError(subject)
    _enforce(op, mode, actor, scope=subject, block_exposure=block_exposure)
