"""Cross-scope memory sharing under owner consent (ADR-080 part C / SPEC-242)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Literal, Protocol

from maistro.memory.types import EpisodicMemory, MemoryScope
from maistro.types.memory import SCOPE_RANK

ConsentStatus = Literal["pending", "approved", "rejected"]


class Principal(Protocol):
    """The identity of a memory reader, for scope/agent-boundary checks."""

    scope: MemoryScope
    agent_id: str | None
    user_id: str | None


@dataclass(frozen=True)
class ConsentTask:
    """A pending request to widen a memory's scope, awaiting owner/admin approval."""

    memory_id: str
    summary: str
    current_scope: MemoryScope
    target_scope: MemoryScope
    owner: str
    status: ConsentStatus = "pending"


class ScopeNarrowingError(ValueError):
    """Raised when a widen is proposed to a scope no broader than the current one."""


def _is_own_memory(reader: Principal, memory: EpisodicMemory) -> bool:
    """Whether the reader is the exact owner of this memory at its own scope."""
    if memory.scope != reader.scope:
        return False
    if memory.scope == MemoryScope.AGENT:
        return memory.agent_id == reader.agent_id
    if memory.scope == MemoryScope.USER:
        return memory.user_id == reader.user_id
    return True


def can_read(reader: Principal, memory: EpisodicMemory) -> bool:
    """Own-scope reads always pass; wider/cross-agent reads require explicit sharing."""
    if _is_own_memory(reader, memory):
        return True
    return memory.shared and SCOPE_RANK[reader.scope] <= SCOPE_RANK[memory.scope]


def propose_widen(memory: EpisodicMemory, target_scope: MemoryScope) -> ConsentTask:
    """Build a pending ConsentTask widening memory.scope to target_scope (must be broader)."""
    if SCOPE_RANK[target_scope] <= SCOPE_RANK[memory.scope]:
        raise ScopeNarrowingError(
            f"target scope {target_scope} is not broader than current scope {memory.scope}"
        )
    owner = memory.user_id or memory.agent_id or ""
    return ConsentTask(
        memory_id=memory.memory_id,
        summary=memory.content,
        current_scope=memory.scope,
        target_scope=target_scope,
        owner=owner,
    )


def resolve_consent(task: ConsentTask, decision: Literal["approve", "reject"]) -> ConsentTask:
    """Move a pending ConsentTask to approved or rejected."""
    new_status: ConsentStatus = "approved" if decision == "approve" else "rejected"
    return dataclasses.replace(task, status=new_status)


def apply_widen(memory: EpisodicMemory, task: ConsentTask) -> EpisodicMemory:
    """Widen memory.scope and mark it shared, only if task is approved; otherwise a no-op."""
    if task.status != "approved":
        return memory
    return dataclasses.replace(memory, scope=task.target_scope, shared=True)
