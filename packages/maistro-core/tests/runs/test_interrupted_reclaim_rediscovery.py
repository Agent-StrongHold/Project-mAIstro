"""Scope guards for the recovery tick's stranded-reclaim rediscovery (#1863).

The repair in `Container.recover_abandoned_attempts` re-finds a reclaimed
Attempt whose reconciliation a crash interrupted, but rediscovery must stay
narrower than "any terminal Attempt": a FAILED, TIMED_OUT, or
requested-CANCELLED Attempt says a retry decision is owed to its owner, and a
newer Attempt under the same NodeRun means the crash window already healed.
These tests pin both boundaries against the public tick, on the canonical
store backends, and hold the tick to its #1850 counting rule — parking a
stranded Run is persisted progress, but it is not a settlement, so a
rediscovery-only tick reports zero.

The crash window itself is injected at the same seam the #1863
characterization used: the real `reclaim_expired_attempts` commits the
physical CANCELLED and the test simply never reconciles it, which is exactly
the state a process lost between the two halves leaves behind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.types.config import AgentConfig


@pytest.fixture
async def recovery_container(spine: Any) -> Any:
    store, workspace, project_id = spine
    container = await create_container(
        AgentConfig(router_api_key="test-key", database_url="memory://")
    )
    container.run_store = store
    try:
        yield container, workspace, project_id
    finally:
        await container.aclose()


async def _running_run(
    container: Container, workspace: str, project_id: str, *, nodes: list[str]
) -> tuple[str, dict[str, str]]:
    """A RUNNING Run with one RUNNING NodeRun per name; returns (run_id, node ids)."""
    store = container.run_store
    graph = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="rediscovery scope",
        nodes=[Node(node_id=name, node_type="test") for name in nodes],
    )
    run = await store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_ids: dict[str, str] = {}
    for name in nodes:
        node = await store.create_node_run(run.run_id, node_id=name)
        await store.transition_node_run(node.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node.node_run_id, RunStatus.RUNNING)
        node_ids[name] = node.node_run_id
    return run.run_id, node_ids


async def _stranded_reclaim(container: Container, node_run_id: str, *, moment: datetime) -> str:
    """Commit the physical reclaim and stop there: the #1863 crash window."""
    store = container.run_store
    attempt = await store.create_attempt(
        node_run_id,
        executor_id="worker-1",
        lease_holder="worker-1",
        lease_ttl=timedelta(seconds=30),
    )
    assert attempt.execution_lease is not None
    attempt = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    (reclaimed,) = await store.reclaim_expired_attempts(now=moment)
    assert reclaimed.attempt_id == attempt.attempt_id
    assert reclaimed.status is AttemptStatus.CANCELLED
    return attempt.attempt_id


def _forbid_dispatch(container: Container, monkeypatch: pytest.MonkeyPatch) -> None:
    """Recovery consumes persisted facts; it must never mint physical work."""
    store = container.run_store
    for name in ("create_attempt", "create_node_run"):
        monkeypatch.setattr(store, name, AsyncMock(side_effect=AssertionError("dispatch")))
    monkeypatch.setattr(
        container.invocation_store,
        "create",
        AsyncMock(side_effect=AssertionError("invocation dispatch")),
    )


@pytest.mark.parametrize(
    ("terminal", "evidence"),
    [
        (AttemptStatus.FAILED, "the work failed"),
        (AttemptStatus.TIMED_OUT, "the work exceeded its deadline"),
        (AttemptStatus.CANCELLED, "a person cancelled this"),
    ],
    ids=["failed", "timed-out", "requested-cancelled"],
)
async def test_recovery_tick_leaves_retry_owned_terminals_to_their_owner(
    recovery_container: Any,
    monkeypatch: pytest.MonkeyPatch,
    terminal: AttemptStatus,
    evidence: str,
) -> None:
    """A terminal Attempt without reclaim evidence is nobody's recovery case.

    The lease sweep's own error text is what marks an Attempt as reclaim
    evidence; a FAILED, TIMED_OUT, or requested-CANCELLED row records a
    decision someone owes or made, and the tick must not park over it.
    """
    container, workspace, project_id = recovery_container
    store = container.run_store
    run_id, node_ids = await _running_run(container, workspace, project_id, nodes=["a"])
    attempt = await store.create_attempt(node_ids["a"])
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(attempt.attempt_id, terminal, error=evidence)
    _forbid_dispatch(container, monkeypatch)

    assert (
        await container.recover_abandoned_attempts(now=datetime.now(UTC) + timedelta(hours=1)) == 0
    )

    run = await store.get_run(run_id)
    node = await store.get_node_run(node_ids["a"])
    assert run is not None and run.status is RunStatus.RUNNING
    assert node is not None and node.status is RunStatus.RUNNING
    assert await store.get_attempt(attempt.attempt_id) == attempt


async def test_recovery_tick_does_not_park_behind_a_newer_attempt(
    recovery_container: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reclaimed Attempt a newer Attempt supersedes is not rediscovered.

    If a newer Attempt exists under the NodeRun, the crash window already
    healed: someone re-attempted the node after the reclaim. Parking over the
    newer Attempt's work would substitute a stale recovery artefact for the
    decision its owner is about to write.
    """
    container, workspace, project_id = recovery_container
    store = container.run_store
    run_id, node_ids = await _running_run(container, workspace, project_id, nodes=["a"])
    moment = datetime.now(UTC) + timedelta(hours=1)
    await _stranded_reclaim(container, node_ids["a"], moment=moment)
    newer = await store.create_attempt(node_ids["a"])
    newer = await store.transition_attempt(newer.attempt_id, AttemptStatus.RUNNING)
    _forbid_dispatch(container, monkeypatch)

    assert await container.recover_abandoned_attempts(now=moment) == 0

    run = await store.get_run(run_id)
    node = await store.get_node_run(node_ids["a"])
    assert run is not None and run.status is RunStatus.RUNNING
    assert node is not None and node.status is RunStatus.RUNNING
    assert await store.get_attempt(newer.attempt_id) == newer


async def test_rediscovery_parks_only_its_own_node(
    recovery_container: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One stranded node parks alone while a leased sibling still runs.

    The Run is only parked once nothing under it is active, so a sibling
    NodeRun holding an unexpired lease keeps the Run RUNNING through the tick
    that heals the stranded node. Expiring the sibling's lease lets the next
    tick finish the job through the ordinary reclaim-and-reconcile path.
    """
    container, workspace, project_id = recovery_container
    store = container.run_store
    run_id, node_ids = await _running_run(container, workspace, project_id, nodes=["a", "b"])
    moment = datetime.now(UTC) + timedelta(hours=1)
    await _stranded_reclaim(container, node_ids["a"], moment=moment)
    sibling = await store.create_attempt(
        node_ids["b"],
        executor_id="worker-2",
        lease_holder="worker-2",
        lease_ttl=timedelta(hours=2),
    )
    assert sibling.execution_lease is not None
    sibling = await store.transition_attempt(
        sibling.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=sibling.execution_lease.fencing_token,
    )
    _forbid_dispatch(container, monkeypatch)

    assert await container.recover_abandoned_attempts(now=moment) == 0

    stranded = await store.get_node_run(node_ids["a"])
    active = await store.get_node_run(node_ids["b"])
    run = await store.get_run(run_id)
    assert stranded is not None and stranded.status is RunStatus.WAITING
    assert active is not None and active.status is RunStatus.RUNNING
    assert run is not None and run.status is RunStatus.RUNNING

    # Once the sibling's lease lapses too, the run parks and reports the work.
    assert await container.recover_abandoned_attempts(now=moment + timedelta(hours=3), limit=1) == 1
    healed = await store.get_run(run_id)
    assert healed is not None and healed.status is RunStatus.WAITING
    settled_sibling = await store.get_attempt(sibling.attempt_id)
    assert settled_sibling is not None and settled_sibling.status is AttemptStatus.CANCELLED
