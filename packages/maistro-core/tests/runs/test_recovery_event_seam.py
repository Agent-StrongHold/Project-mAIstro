"""The abandoned-Attempt sweeps announce through the one canonical authority (#2468).

`create_container` hands both production recovery halves — the lease sweep and
the terminal-Attempt replay — the composition root's
`CanonicalRecoveryEventSink`, so every disposition persists through the
backend-selected EventEnvelope store *before* the legacy bus observes it as a
downstream projection. These tests pin that seam on the real Container:

- the composition sink is the seam while its Run store is live, and a
  crash-window replica that swaps the Run store re-binds through the same
  canonical publisher — never a second identity authority;
- a hand-built Container with a stale sink but no canonical publisher keeps
  that legacy-only sink, and one with no authority at all keeps its bare bus;
  nothing canonical is invented for either;
- the sweep's fact is persisted canonically first with the full
  Workspace/Project/Run/NodeRun/Attempt correlation, and the legacy trigger
  receives the *same* fact afterwards carrying the persisted identity — if the
  wiring ever regresses to announcing on the bare bus, no canonical envelope
  exists and these oracles fail;
- a retry sweep and a replica re-announce cannot mint a second Workspace
  sequence or re-fire the legacy projection (the deterministic event_id
  dedupes, and only the inserting append projects);
- a canonical append failure is loud, claims nothing, leaves the physical
  disposition settled, and reconciles idempotently once the store heals;
- a reclaim whose reconciliation a crash interrupted is rediscovered by the
  replay half and announced canonically, not only on the bus.

The PostgreSQL Container oracle for the same contract lives in
`test_pg_recovery_disposition_events.py`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from maistro.container import Container, create_container
from maistro.events.bus import Event, EventBus
from maistro.events.envelope import EventEnvelope, InMemoryEventStore
from maistro.events.publisher import CANONICAL_EVENT_METADATA
from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, CancellationCause, RunStatus
from maistro.runs.recovery_events import (
    RECOVERY_EVENT_TYPE,
    CanonicalRecoveryEventSink,
    RecoveryDispositionEvent,
    _recovery_event_id,
    recovery_event,
)
from maistro.runs.store import InMemoryRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.types.config import AgentConfig

_WORKSPACE = "ws-recovery-seam"


class _RecordingSink:
    """Records canonical envelopes handed to a sink behind no real store."""

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope] = []

    async def emit(self, event: EventEnvelope) -> EventEnvelope:
        self.envelopes.append(event)
        return event


class _BusSpy:
    """Records the legacy Events the bus delivers, in delivery order."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def __call__(self, event: Event) -> None:
        self.events.append(event)


class _FailingThenHealedStore(InMemoryEventStore):
    """The real store behind a fault: appends refuse until ``healed``.

    Subclasses the concrete in-memory store so the publisher's structural
    `EventAppendDispositionStore` check keeps holding while the fault is in.
    Reads always delegate to the real store, so the oracle sees exactly what
    a reader of the durable authority would see.
    """

    def __init__(self, inner: InMemoryEventStore) -> None:
        super().__init__()
        self._inner = inner
        self.healed = False
        self.refused = 0

    async def append_with_disposition(self, event: EventEnvelope) -> Any:
        if not self.healed:
            self.refused += 1
            raise RuntimeError("canonical event store unavailable")
        return await self._inner.append_with_disposition(event)

    async def get(self, event_id: str) -> EventEnvelope | None:
        return await self._inner.get(event_id)

    async def list_stream(
        self, stream_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> list[EventEnvelope]:
        return await self._inner.list_stream(stream_id, after_sequence=after_sequence, limit=limit)


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


async def _expired_running_attempt(
    container: Container, workspace_id: str
) -> tuple[str, str, str, Any]:
    """A RUNNING Run/NodeRun holding one leased Attempt; returns (run, node, attempt ids, after)."""
    store = container.run_store
    # The admission fence (#37) refuses a Root Project for a Workspace id
    # nothing canonical owns, so provision the Workspace the way the
    # container itself does at composition: `create` files the Root Project
    # that `create_root` then treats as create-or-return.
    if await container.workspace_store.get(workspace_id) is None:
        await container.workspace_store.create(
            creator_user_id="test", name=workspace_id, workspace_id=workspace_id
        )
    root = await container.project_scope_store.create_root(workspace_id)
    graph = Graph(
        workspace_id=workspace_id,
        project_id=root.project_id,
        name="one step",
        nodes=[Node(node_id="step", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        run = await store.transition_run(run.run_id, status)
    node_run = await store.create_node_run(run.run_id, node_id="step")
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        node_run = await store.transition_node_run(node_run.node_run_id, status)
    attempt = await store.create_attempt(
        node_run.node_run_id, lease_holder="worker-seam", lease_ttl=timedelta(seconds=30)
    )
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    return (
        run.run_id,
        node_run.node_run_id,
        attempt.attempt_id,
        lease.expires_at + timedelta(seconds=1),
    )


def _announced_fact(attempt: Any, node_run: Any) -> RecoveryDispositionEvent:
    """The exact fact the sweep announces for a recovered-and-parked Attempt."""
    return recovery_event(
        attempt=attempt,
        node_run=node_run,
        cancellation=CancellationCause.RECOVERED,
        source="maistro.container.recover_abandoned_attempts",
    )


# --- the seam the production sweeps reconcile through -------------------------


async def test_the_composition_sink_is_the_seam_while_its_store_is_live() -> None:
    container = await _container()

    assert container.recovery_event_sink is not None
    assert container._recovery_events() is container.recovery_event_sink


async def test_a_swapped_run_store_rebinds_through_the_canonical_publisher() -> None:
    """A recovery replica that swaps the Run store re-binds over one publisher.

    Crash-window harnesses model a restart by pointing the Container at an
    independent store. The seam must follow the live store while keeping the
    same canonical publisher — the one durable authority — so a replayed
    disposition looks up scope and persists identity where the recovery
    actually reads, never through a stale adapter or a second store.
    """
    container = await _container()
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-recovery-seam-replica")
    replacement = InMemoryRunStore(project_store=projects)
    container.run_store = replacement

    seam = container._recovery_events()

    assert isinstance(seam, CanonicalRecoveryEventSink)
    assert seam is not container.recovery_event_sink
    assert seam._runs is replacement
    assert seam._events is container.canonical_event_publisher

    # The re-bound seam announces facts for Runs the live store owns, into the
    # publisher's durable store — the same object the rest of the Container
    # persists canonical events through.
    graph = Graph(
        workspace_id="ws-recovery-seam-replica",
        project_id=root.project_id,
        name="replica step",
        nodes=[Node(node_id="step", node_type="agent")],
    )
    run = await replacement.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    fact = RecoveryDispositionEvent(
        run_id=run.run_id,
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        attempt_status="cancelled",
        node_run_status="running",
        cancellation_cause="recovered",
        disposition="recovered_and_parked",
        error="worker exited",
        source="recovery-seam-test",
    )
    envelope = await seam.emit(fact)

    assert envelope.workspace_id == "ws-recovery-seam-replica"
    assert envelope.run_id == run.run_id
    persisted = await container.canonical_event_publisher.store.get(envelope.event_id)
    assert persisted is not None
    assert persisted.sequence == 1


async def test_a_stale_sink_without_a_canonical_publisher_is_still_returned() -> None:
    """A hand-built Container with a sink but no publisher keeps that sink.

    There is no canonical store behind this wiring to re-bind through, and the
    seam must not invent one: the legacy-only projection is the honest ceiling
    of a Container someone assembled without the composition root.
    """
    stale_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
    sink = CanonicalRecoveryEventSink(stale_store, _RecordingSink())
    container = Container.__new__(Container)
    container.recovery_event_sink = sink
    container.canonical_event_publisher = None
    container.run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
    container.event_bus = EventBus()

    assert container._recovery_events() is sink
    assert container.canonical_event_publisher is None


async def test_a_hand_built_container_without_a_canonical_authority_keeps_its_bus() -> None:
    """No sink and no publisher: the reconcilers announce on the bare bus.

    A hand-built Container that wired no canonical authority sweeps exactly as
    it did before #2468 — legacy projection only, no envelope, no second
    authority minted behind its back.
    """
    container = Container.__new__(Container)
    container.recovery_event_sink = None
    container.canonical_event_publisher = None
    bus = EventBus()
    container.run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
    container.event_bus = bus

    assert container._recovery_events() is bus


# --- the sweep persists first; the bus is a downstream projection ------------


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_the_sweep_persists_the_disposition_before_the_bus_observes_it() -> None:
    """An expired RUNNING Attempt sweeps to exactly one canonical envelope.

    Negative oracle for #2468: the announcement runs through the composition
    root's sink, so the canonical envelope exists with the full
    Workspace/Project/Run/NodeRun/Attempt correlation and the legacy Event the
    bus delivers is its projection — same event_id, sequence attached. A
    wiring regressed to `events=self.event_bus` mints no envelope at all and
    fails every assertion below.
    """
    container = await _container()
    spy = _BusSpy()
    container.event_bus.subscribe(spy)
    run_id, node_run_id, attempt_id, after = await _expired_running_attempt(container, _WORKSPACE)

    assert await container.recover_abandoned_attempts(now=after) == 1

    settled = await container.run_store.get_attempt(attempt_id)
    parked = await container.run_store.get_node_run(node_run_id)
    assert settled is not None and settled.status is AttemptStatus.CANCELLED
    assert parked is not None and parked.status is RunStatus.WAITING

    fact = _announced_fact(settled, parked)
    expected_id = _recovery_event_id(fact)
    store: InMemoryEventStore = container.canonical_event_publisher.store

    envelope = await store.get(expected_id)
    assert envelope is not None
    assert envelope.type == RECOVERY_EVENT_TYPE
    assert envelope.sequence == 1
    assert envelope.workspace_id == _WORKSPACE
    assert envelope.project_id
    assert envelope.run_id == run_id
    assert envelope.node_run_id == node_run_id
    assert envelope.attempt_id == attempt_id
    assert envelope.correlation_id == run_id
    assert envelope.source == "maistro.container.recover_abandoned_attempts"
    assert envelope.payload["disposition"] == "recovered_and_parked"
    assert envelope.payload["cancellation_cause"] == "recovered"
    assert envelope.payload["node_run_status"] == RunStatus.WAITING.value
    stream = await store.list_stream(f"workspace:{_WORKSPACE}")
    assert [event.event_id for event in stream] == [expected_id]

    # The legacy trigger receives the same fact, after the durable append,
    # carrying the persisted identity — not an independently minted Event.
    assert len(spy.events) == 1
    legacy = spy.events[0]
    assert legacy.event_id == expected_id
    assert legacy.event_type == RECOVERY_EVENT_TYPE
    assert legacy.payload["disposition"] == "recovered_and_parked"
    assert legacy.payload[CANONICAL_EVENT_METADATA]["sequence"] == 1
    assert legacy.payload[CANONICAL_EVENT_METADATA]["event_id"] == expected_id

    # The composition wiring delivered it — no test-only sink substituted.
    assert container._recovery_events() is container.recovery_event_sink


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_a_retry_sweep_and_a_replica_reannounce_cannot_duplicate_the_fact() -> None:
    """Repeated sweeps and replica re-announces stay one identity, one delivery."""
    container = await _container()
    spy = _BusSpy()
    container.event_bus.subscribe(spy)
    _run_id, node_run_id, attempt_id, after = await _expired_running_attempt(container, _WORKSPACE)

    assert await container.recover_abandoned_attempts(now=after) == 1
    settled = await container.run_store.get_attempt(attempt_id)
    parked = await container.run_store.get_node_run(node_run_id)
    fact = _announced_fact(settled, parked)
    event_id = _recovery_event_id(fact)
    store: InMemoryEventStore = container.canonical_event_publisher.store

    # The second sweep reclaims nothing and announces nothing new.
    assert await container.recover_abandoned_attempts(now=after) == 0
    assert await store.get(event_id) is not None
    assert len(spy.events) == 1

    # A recovery replica that rediscovers the same settled Attempt re-announces
    # the same logical disposition through the same seam: the store dedupes on
    # the deterministic event_id, so no second Workspace sequence is allocated
    # and the non-inserting append does not project onto the bus again.
    await container.recovery_event_sink.emit(fact)
    await container.recovery_event_sink.emit(fact)

    replayed = await store.get(event_id)
    assert replayed is not None
    assert replayed.sequence == 1
    stream = await store.list_stream(f"workspace:{_WORKSPACE}")
    assert [event.event_id for event in stream] == [event_id]
    assert len(spy.events) == 1


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_a_canonical_append_failure_claims_nothing_and_stays_reconcilable() -> None:
    """A store fault is loud, delivers nothing, and heals idempotently.

    The physical disposition persists before the announcement runs, so the
    sweep raising means: recovery state is truthful and inspectable, no
    canonical envelope exists to mistake for delivered, no legacy trigger
    fired — and once the store heals, the same logical disposition lands once
    under the identity it always had.
    """
    container = await _container()
    spy = _BusSpy()
    container.event_bus.subscribe(spy)
    _run_id, node_run_id, attempt_id, after = await _expired_running_attempt(container, _WORKSPACE)
    failing = _FailingThenHealedStore(container.canonical_event_publisher.store)
    container.canonical_event_publisher._store = failing

    with pytest.raises(RuntimeError, match="canonical event store unavailable"):
        await container.recover_abandoned_attempts(now=after)

    assert failing.refused == 1

    # The physical disposition did settle — the recovery decision itself is
    # durable and inspectable even though its announcement is not.
    settled = await container.run_store.get_attempt(attempt_id)
    parked = await container.run_store.get_node_run(node_run_id)
    assert settled is not None and settled.status is AttemptStatus.CANCELLED
    assert settled.cancellation_cause is CancellationCause.RECOVERED
    assert parked is not None and parked.status is RunStatus.WAITING

    # Nothing was claimed: no canonical envelope exists to mistake for
    # delivered, and no legacy trigger fired on the failed delivery.
    assert await failing.get(_recovery_event_id(_announced_fact(settled, parked))) is None
    assert spy.events == []

    # Healed: the same logical disposition reconciles through the production
    # seam, exactly once, under the identity it always had.
    failing.healed = True
    fact = _announced_fact(settled, parked)
    envelope = await container._recovery_events().emit(fact)

    expected_id = _recovery_event_id(fact)
    assert envelope.event_id == expected_id
    assert envelope.sequence == 1
    stream = await failing.list_stream(f"workspace:{_WORKSPACE}")
    assert [event.event_id for event in stream] == [expected_id]
    assert [event.event_id for event in spy.events] == [expected_id]


@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_an_interrupted_reclaim_replay_announces_the_canonical_disposition() -> None:
    """A crash between the reclaim commit and reconciliation replays canonically.

    The lease sweep commits the physical CANCELLED+RECOVERED before the
    Container reconciles it; the next tick's replay half must rediscover the
    typed RECOVERED Attempt under the still-RUNNING NodeRun, park it, and
    announce the disposition through the canonical store — not leave the fact
    observable only on the legacy bus (or not at all).
    """
    container = await _container()
    spy = _BusSpy()
    container.event_bus.subscribe(spy)
    run_id, node_run_id, attempt_id, after = await _expired_running_attempt(container, _WORKSPACE)

    # The reclaim half commits; the process is lost before reconciling.
    reclaimed = await container.run_store.reclaim_expired_attempts(now=after)
    assert len(reclaimed) == 1
    assert await container.run_store.get_node_run(node_run_id) is not None

    # The next tick's replay half heals the window. (The sweep's return counts
    # accepted outcomes and Run settlements; a recovery park is neither, so the
    # meaningful oracle is the parked state and the canonical fact below.)
    await container.recover_abandoned_attempts(now=after)

    parked = await container.run_store.get_node_run(node_run_id)
    parked_run = await container.run_store.get_run(run_id)
    assert parked is not None and parked.status is RunStatus.WAITING
    assert parked_run is not None and parked_run.status is RunStatus.WAITING

    settled = await container.run_store.get_attempt(attempt_id)
    assert settled is not None and settled.cancellation_cause is CancellationCause.RECOVERED
    fact = _announced_fact(settled, parked)
    expected_id = _recovery_event_id(fact)
    store: InMemoryEventStore = container.canonical_event_publisher.store

    envelope = await store.get(expected_id)
    assert envelope is not None
    assert envelope.sequence == 1
    assert envelope.run_id == run_id
    assert envelope.node_run_id == node_run_id
    assert envelope.attempt_id == attempt_id
    assert envelope.payload["disposition"] == "recovered_and_parked"
    # The canonical append came first; the legacy projection is its downstream.
    assert [event.event_id for event in spy.events] == [expected_id]
