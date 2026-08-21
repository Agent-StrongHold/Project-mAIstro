"""SPEC-182 Phase 1 — import-surface smoke test and lifecycle enqueue round-trip."""

from __future__ import annotations

import pytest


def test_adr_058_public_exports_importable() -> None:
    from maistro.a2a import (
        A2ABroker,
        A2ADelegator,
        A2AError,
        A2ATask,
        DelegationBudget,
        DelegationMode,
        DelegationRefused,
        DelegationResult,
        GuestPeerManager,
        LocalTransport,
        PeerTrust,
        TaskQueue,
        TaskStatus,
        Transport,
    )

    assert issubclass(DelegationRefused, A2AError)
    for exported in (
        A2ABroker,
        A2ADelegator,
        A2ATask,
        DelegationBudget,
        DelegationMode,
        DelegationResult,
        GuestPeerManager,
        LocalTransport,
        PeerTrust,
        TaskQueue,
        TaskStatus,
        Transport,
    ):
        assert exported is not None


def test_all_names_resolve() -> None:
    import maistro.a2a as a2a

    for name in a2a.__all__:
        assert getattr(a2a, name) is not None


@pytest.mark.asyncio
async def test_enqueue_round_trip_stores_task_id() -> None:
    from maistro.a2a import TaskQueue

    queue = TaskQueue()
    task = {"task": "do x"}
    task_id = await queue.enqueue(task, priority="P1")
    dequeued = await queue.dequeue()
    assert dequeued is not None
    assert dequeued["id"] == task_id


def test_delegator_persists_metadata() -> None:
    from maistro.a2a import A2ADelegator, DelegationMode

    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    task_id = delegator.delegate_task(
        "planner",
        "x",
        "coder",
        delegation_mode=DelegationMode.ALLOW_LIST,
        metadata={"source": "test"},
    )
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.metadata == {"source": "test"}
