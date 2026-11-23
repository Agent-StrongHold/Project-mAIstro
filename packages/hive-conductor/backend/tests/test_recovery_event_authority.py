"""Product recovery must persist through canonical EventEnvelope before legacy fanout.

Regression oracles for #2468. These focus on the real production wrapper calls,
not a test-only direct call to CanonicalRecoveryEventSink. Real PostgreSQL
restarts/concurrent-connection evidence remains a separate M1 closure gate.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from maistro.events.bus import EventBus
from maistro.events.envelope import InMemoryEventStore
from maistro.events.publisher import CANONICAL_EVENT_METADATA, CanonicalEventPublisher
from maistro.runs.recovery_events import (
    RECOVERY_EVENT_TYPE,
    CanonicalRecoveryEventSink,
    RecoveryDispositionEvent,
    _recovery_event_id,
)
from services.recovery_event_authority import recovery_events_for

pytestmark = pytest.mark.contract("behavioral")

_RUN_ID = "product-recovery-run"
_WORKSPACE = "ws-product-recovery"


class _RunLookup:
    """Canonical Run scope is required before appending a recovery envelope."""

    async def get_run(self, run_id: str) -> Any | None:
        if run_id != _RUN_ID:
            return None
        return SimpleNamespace(
            run_id=_RUN_ID,
            workspace_id=_WORKSPACE,
            project_id="proj-product-recovery",
        )


def _fact() -> RecoveryDispositionEvent:
    return RecoveryDispositionEvent(
        run_id=_RUN_ID,
        node_run_id="node-recovery",
        attempt_id="attempt-recovery",
        attempt_status="cancelled",
        node_run_status="waiting",
        cancellation_cause="recovered",
        disposition="recovered_and_parked",
        error="lost worker",
        source="test.product-recovery",
    )


def _owner() -> tuple[SimpleNamespace, InMemoryEventStore, list[Any]]:
    store = InMemoryEventStore()
    bus = EventBus()
    observed: list[Any] = []

    async def inspect(event: Any) -> None:
        # The canonical event must already exist when the compatibility
        # subscriber observes the same logical disposition.
        assert await store.get(event.event_id) is not None
        observed.append(event)

    bus.subscribe(inspect)
    owner = SimpleNamespace(
        run_store=_RunLookup(),
        graph_run_store=object(),
        canonical_event_publisher=CanonicalEventPublisher(store, legacy_bus=bus),
        event_bus=bus,
        guest_peers=None,
        harness_adapters={},
    )
    return owner, store, observed


async def _assert_canonical_receipt(
    store: InMemoryEventStore, observed: list[Any]
) -> None:
    fact = _fact()
    event_id = _recovery_event_id(fact)
    persisted = await store.get(event_id)
    assert persisted is not None
    assert persisted.type == RECOVERY_EVENT_TYPE
    assert persisted.event_id == event_id
    assert persisted.sequence == 1
    assert persisted.workspace_id == _WORKSPACE
    assert persisted.project_id == "proj-product-recovery"
    assert persisted.run_id == _RUN_ID
    assert persisted.node_run_id == fact.node_run_id
    assert persisted.attempt_id == fact.attempt_id
    assert [row.event_id for row in await store.list_stream(f"workspace:{_WORKSPACE}")] == [
        event_id
    ]
    assert [row.event_id for row in observed] == [event_id]
    assert observed[0].payload[CANONICAL_EVENT_METADATA]["sequence"] == 1


def test_configured_container_selector_keeps_its_live_store_rebinding() -> None:
    sink = object()
    owner = SimpleNamespace(_recovery_events=lambda: sink, event_bus=object())
    assert recovery_events_for(owner) is sink


def test_unconfigured_standalone_owner_retains_legacy_projection_only() -> None:
    bus = EventBus()
    assert recovery_events_for(SimpleNamespace(event_bus=bus)) is bus


def test_canonical_publisher_without_run_lookup_never_falls_back_to_legacy() -> None:
    store = InMemoryEventStore()
    owner = SimpleNamespace(
        canonical_event_publisher=CanonicalEventPublisher(store),
        event_bus=EventBus(),
    )
    with pytest.raises(RuntimeError, match="canonical RunStore unavailable"):
        recovery_events_for(owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_point", ["recover", "wake", "polled_completion"])
async def test_registered_dag_production_recovery_persists_canonical_event(
    monkeypatch: pytest.MonkeyPatch, entry_point: str
) -> None:
    import services.registered_dag_recovery as recovery

    owner, store, observed = _owner()
    monkeypatch.setattr(recovery, "_container", lambda: owner)

    async def emit_disposition(**kwargs: Any) -> int:
        assert isinstance(kwargs["events"], CanonicalRecoveryEventSink)
        await kwargs["events"].emit(_fact())
        return 1

    if entry_point == "recover":
        monkeypatch.setattr(recovery, "recover_queued_graph_runs", emit_disposition)
        assert await recovery.recover_stranded_registered_dag_runs() == 1
    elif entry_point == "wake":
        monkeypatch.setattr(recovery, "resume_due_graph_runs", emit_disposition)
        assert await recovery.wake_due_registered_dag_runs() == 1
    else:
        # The external poll writes a completion, then same-tick QUEUED
        # recovery must also preserve the canonical Event publisher.
        owner.guest_peers = object()

        async def delivered(**kwargs: Any) -> int:
            return 1

        async def no_timed_wake(**kwargs: Any) -> int:
            return 0

        monkeypatch.setattr(recovery, "poll_external_results", delivered)
        monkeypatch.setattr(recovery, "recover_queued_graph_runs", emit_disposition)
        monkeypatch.setattr(recovery, "resume_due_graph_runs", no_timed_wake)
        assert await recovery.wake_due_registered_dag_runs() == 1

    await _assert_canonical_receipt(store, observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_point", ["recover", "wake"])
async def test_evolve_production_recovery_persists_canonical_event(
    monkeypatch: pytest.MonkeyPatch, entry_point: str
) -> None:
    import services.evolution_graph as evolution

    owner, store, observed = _owner()
    monkeypatch.setattr(evolution, "canonical_execution_owner", lambda: owner)
    monkeypatch.setattr(evolution, "_current_evolution_service", lambda: None)

    async def emit_disposition(**kwargs: Any) -> int:
        assert isinstance(kwargs["events"], CanonicalRecoveryEventSink)
        await kwargs["events"].emit(_fact())
        return 1

    if entry_point == "recover":
        monkeypatch.setattr(evolution, "recover_queued_graph_runs", emit_disposition)
        assert await evolution.recover_stranded_evolution_runs() == 1
    else:
        monkeypatch.setattr(evolution, "resume_due_graph_runs", emit_disposition)
        assert await evolution.wake_due_evolution_runs() == 1

    await _assert_canonical_receipt(store, observed)


@pytest.mark.asyncio
async def test_duplicate_recovery_disposition_does_not_refire_legacy_bus() -> None:
    owner, store, observed = _owner()
    sink = recovery_events_for(owner)
    assert isinstance(sink, CanonicalRecoveryEventSink)

    await sink.emit(_fact())
    await sink.emit(_fact())

    await _assert_canonical_receipt(store, observed)


@pytest.mark.asyncio
async def test_canonical_append_failure_does_not_fire_legacy_bus() -> None:
    owner, _store, observed = _owner()
    publisher = owner.canonical_event_publisher

    class _UnavailableStore(InMemoryEventStore):
        async def append_with_disposition(self, event: Any) -> Any:
            raise RuntimeError("canonical store offline")

    publisher._store = _UnavailableStore()
    with pytest.raises(RuntimeError, match="canonical store offline"):
        await recovery_events_for(owner).emit(_fact())
    assert observed == []
