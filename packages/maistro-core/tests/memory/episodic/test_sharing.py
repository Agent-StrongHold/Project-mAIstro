"""Tests for cross-scope sharing under owner consent (SPEC-242 / ADR-080 part C)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from maistro.memory.episodic.sharing import (
    ScopeNarrowingError,
    apply_widen,
    can_read,
    propose_widen,
    resolve_consent,
)
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier


@dataclass
class _Reader:
    scope: MemoryScope
    agent_id: str | None = None
    user_id: str | None = None


def _mem(
    scope: MemoryScope = MemoryScope.AGENT,
    agent_id: str | None = "agent-1",
    user_id: str | None = None,
    shared: bool = False,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id="m1",
        tier=MemoryTier.OBSERVATION,
        weight=0.3,
        content="learned something",
        scope=scope,
        agent_id=agent_id,
        user_id=user_id,
        shared=shared,
    )


def test_can_read_own_exact_scope() -> None:
    mem = _mem(scope=MemoryScope.AGENT, agent_id="agent-1")
    reader = _Reader(scope=MemoryScope.AGENT, agent_id="agent-1")

    assert can_read(reader, mem) is True


def test_can_read_wider_scope_only_when_shared() -> None:
    mem = _mem(scope=MemoryScope.TEAM, agent_id=None, shared=False)
    reader = _Reader(scope=MemoryScope.USER)

    assert can_read(reader, mem) is False

    shared_mem = _mem(scope=MemoryScope.TEAM, agent_id=None, shared=True)
    assert can_read(reader, shared_mem) is True


def test_can_read_cross_agent_denied_even_at_same_scope_unless_shared() -> None:
    mem = _mem(scope=MemoryScope.AGENT, agent_id="agent-1", shared=False)
    other_agent_reader = _Reader(scope=MemoryScope.AGENT, agent_id="agent-2")

    assert can_read(other_agent_reader, mem) is False

    shared_mem = _mem(scope=MemoryScope.AGENT, agent_id="agent-1", shared=True)
    assert can_read(other_agent_reader, shared_mem) is True


def test_propose_widen_rejects_narrowing() -> None:
    mem = _mem(scope=MemoryScope.TEAM, agent_id=None, user_id="owner-1")

    with pytest.raises(ScopeNarrowingError):
        propose_widen(mem, MemoryScope.AGENT)


def test_propose_widen_to_broader_scope_builds_pending_task() -> None:
    mem = _mem(scope=MemoryScope.AGENT, agent_id="agent-1")

    task = propose_widen(mem, MemoryScope.TEAM)

    assert task.status == "pending"
    assert task.current_scope == MemoryScope.AGENT
    assert task.target_scope == MemoryScope.TEAM


def test_approved_consent_widens_scope_and_marks_shared() -> None:
    mem = _mem(scope=MemoryScope.AGENT, agent_id="agent-1")
    task = propose_widen(mem, MemoryScope.TEAM)

    approved = resolve_consent(task, "approve")
    widened = apply_widen(mem, approved)

    assert widened.scope == MemoryScope.TEAM
    assert widened.shared is True


def test_rejected_consent_leaves_memory_unchanged() -> None:
    mem = _mem(scope=MemoryScope.AGENT, agent_id="agent-1")
    task = propose_widen(mem, MemoryScope.TEAM)

    rejected = resolve_consent(task, "reject")
    unchanged = apply_widen(mem, rejected)

    assert unchanged.scope == MemoryScope.AGENT
    assert unchanged.shared is False


def test_apply_widen_is_noop_on_pending_task() -> None:
    mem = _mem(scope=MemoryScope.AGENT, agent_id="agent-1")
    task = propose_widen(mem, MemoryScope.TEAM)

    unchanged = apply_widen(mem, task)

    assert unchanged.scope == MemoryScope.AGENT
