"""Replayable canonical-Envelope -> durable-log projection (#2506).

The bridge from the persist-first publisher into the ADR-086 durable trigger
log was the log's *only* ingress, and it was at-most-once: a durable-log
append that failed after the canonical append committed left a persisted
canonical Event permanently invisible to the only processor that could turn
it into trigger delivery, because the retry emission returns
``inserted=False`` and suppresses the legacy bus forever.

These tests hold the repair to the issue's shape: the bridge stays
at-most-once compatibility delivery, and healing happens only through the
ordinary production replay tick (`project_canonical_events`, ticked by
`Container.process_durable_events`) — never a direct bus emit or a test-only
repair call. A regression that removes the projector and restores
"``if outcome.inserted: legacy_bus.emit(...)`` as the whole story" fails
`test_a_publisher_without_a_projection_registry_cannot_heal` and every
heal assertion below.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite
import pytest

from maistro.events.bus import EventBus, EventSubscriberFailure, Trigger
from maistro.events.durable_log import InMemoryEventLog, SqliteEventLog
from maistro.events.envelope import EventEnvelope, InMemoryEventStore, SqliteEventStore
from maistro.events.processing import (
    InMemoryCanonicalProjectionStore,
    InMemoryProjectionFailureStore,
    ProjectionLease,
    project_canonical_events,
)
from maistro.events.publisher import (
    CANONICAL_EVENT_METADATA,
    CanonicalEventPublisher,
    canonical_log_append_kwargs,
)
from maistro.events.trigger_store import TriggerDefinition
from maistro.sqlite_schema import execute_schema_script

POISON = RuntimeError("durable log unavailable")


def _fail_first(count: int) -> Any:
    """A guard that fails the first ``count`` append attempts, then yields.

    The issue's fault is a durable log that is unavailable at emit time and
    healthy afterwards: the bridge append (attempt 1) raises after the
    canonical commit, and every later attempt — the projector's — succeeds.
    """
    seen = {"attempts": 0}

    def guard(_kwargs: Any) -> bool:
        seen["attempts"] += 1
        return seen["attempts"] <= count

    return guard


def _event(event_id: str, workspace: str = "workspace-2506") -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        type="agent.recovery",
        workspace_id=workspace,
        run_id="run-2506",
        correlation_id="run-2506",
        source="test",
        provenance={"legacy_event_category": "agent"},
        payload={"disposition": "recovered"},
    )


def _wired_bridge(log: Any) -> EventBus:
    """The legacy bus with the container's authoritative bridge subscribed.

    Mirrors `create_container`'s `_persist_bus_event` exactly: every bus
    emission is appended into the durable log through
    `append_from_bus_event` (which keys canonical projections by their
    source `event_id`), before any trigger can claim success.
    """
    from maistro.events.durable_log import append_from_bus_event

    bus = EventBus()

    async def persist_bus_event(event: Any) -> None:
        await log.append(**append_from_bus_event(event))

    bus.subscribe(persist_bus_event, before_handlers=True)
    return bus


def _publisher(
    store: Any,
    *,
    log: Any,
    registry: Any | None,
    bus: EventBus | None = None,
    fail_while: Any | None = None,
) -> CanonicalEventPublisher:
    """A publisher wired the way the container wires one, with a poisoned log.

    The poisoning wrapper is the fault the issue describes: the canonical
    append succeeds, then the authoritative durable-log append throws (while
    ``fail_while`` holds for the row being appended), and the bus (correctly)
    raises `EventSubscriberFailure` before any trigger can claim success.
    Both ingress paths — the bridge and the projector — go through this one
    append, exactly as they do in production.
    """
    original = log.append
    guard = fail_while if fail_while is not None else (lambda kwargs: True)

    async def poisoned(event_type: str, **kwargs: Any) -> Any:
        if event_type == "agent.recovery" and guard(kwargs):
            raise POISON
        return await original(event_type, **kwargs)

    log.append = poisoned  # type: ignore[method-assign]
    return CanonicalEventPublisher(
        store,
        legacy_bus=bus if bus is not None else _wired_bridge(log),
        projection_registry=registry,
    )


async def _tick(*, registry: Any, failures: Any, store: Any, log: Any, holder: str) -> Any:
    from maistro.events.publisher import canonical_log_append_kwargs

    return await project_canonical_events(
        projection_store=registry,
        event_store=store,
        event_log=log,
        failure_store=failures,
        append_kwargs=canonical_log_append_kwargs,
        holder=holder,
    )


async def test_a_bridge_failure_after_the_canonical_commit_heals_on_the_tick() -> None:
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    registry = InMemoryCanonicalProjectionStore(store)
    failures = InMemoryProjectionFailureStore()
    publisher = _publisher(store, log=log, registry=registry, fail_while=_fail_first(1))

    with pytest.raises(EventSubscriberFailure):
        await publisher.emit(_event("heal-me"))

    # The canonical Event is durable; the ADR-086 log has nothing (the bridge
    # raised before any row), and the poisoned append is what raised.
    assert (await store.get("heal-me")) is not None
    assert (await store.get("heal-me")).sequence == 1  # type: ignore[union-attr]
    assert await log.query(event_type="agent.recovery") == []

    outcome = await _tick(registry=registry, failures=failures, store=store, log=log, holder="r1")

    rows = await log.query(event_type="agent.recovery")
    assert len(rows) == 1
    metadata = rows[0].payload[CANONICAL_EVENT_METADATA]
    assert metadata["event_id"] == "heal-me"
    assert metadata["sequence"] == 1
    assert metadata["workspace_id"] == "workspace-2506"
    assert outcome.projected == 1
    assert outcome.cursors == {"workspace:workspace-2506": 1}
    # The healed row is the shape the bridge writes: same mapping, keyed by
    # the canonical identity so it can never duplicate the bridge's row.
    assert canonical_log_append_kwargs(await store.get("heal-me"))["source_event_id"] == "heal-me"


async def test_a_retry_emission_after_failure_cannot_skip_log_delivery() -> None:
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    registry = InMemoryCanonicalProjectionStore(store)
    failures = InMemoryProjectionFailureStore()
    publisher = _publisher(
        store,
        log=log,
        registry=registry,
        fail_while=_fail_first(1),
    )
    event = _event("retried-emission")

    with pytest.raises(EventSubscriberFailure):
        await publisher.emit(event)
    # The retry of the identical event_id dedupes at the canonical store and
    # suppresses the legacy bridge — and still must not skip the log.
    replayed = await publisher.emit(event)
    assert replayed.sequence == 1

    await _tick(registry=registry, failures=failures, store=store, log=log, holder="r1")
    await _tick(registry=registry, failures=failures, store=store, log=log, holder="r1")

    rows = await log.query(event_type="agent.recovery")
    assert [row.payload[CANONICAL_EVENT_METADATA]["event_id"] for row in rows] == [
        "retried-emission"
    ]


async def test_a_log_commit_before_the_cursor_advances_never_duplicates_a_row() -> None:
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    registry = InMemoryCanonicalProjectionStore(store)
    failures = InMemoryProjectionFailureStore()

    emitted: list[str] = []

    async def capture(_trigger: Trigger, event: Any) -> None:
        emitted.append(event.event_id)

    # The container's bus: the authoritative durable-log bridge subscribed,
    # plus an ordinary notification trigger for the same event.
    bus = _wired_bridge(log)
    bus.register_handler("capture", capture)
    bus.add_trigger(
        Trigger(
            name="capture",
            event_types=["agent.recovery"],
            action_type="capture",
            cooldown_seconds=0,
        )
    )
    # A healthy bridge: the canonical append commits and the bridge appends
    # the row (with its canonical source id) before the projector ever runs.
    healthy = CanonicalEventPublisher(store, legacy_bus=bus, projection_registry=registry)
    await healthy.emit(_event("bridged-once"))
    assert emitted == ["bridged-once"]
    assert len(await log.query(event_type="agent.recovery")) == 1

    outcome = await _tick(registry=registry, failures=failures, store=store, log=log, holder="r1")

    rows = await log.query(event_type="agent.recovery")
    assert len(rows) == 1
    assert rows[0].payload[CANONICAL_EVENT_METADATA]["event_id"] == "bridged-once"
    assert outcome.projected == 1
    assert outcome.cursors == {"workspace:workspace-2506": 1}


async def test_registration_places_a_new_stream_at_the_canonical_watermark() -> None:
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    failures = InMemoryProjectionFailureStore()

    # Retained history projected by the pre-projection bridge: three events
    # already delivered, no registration rows, no source ids in the log.
    historical = CanonicalEventPublisher(store, legacy_bus=EventBus())
    for index in range(3):
        await historical.emit(_event(f"history-{index}"))
    assert await log.query(event_type="agent.recovery") == []

    # The projector learns the stream only when the publisher first registers
    # it — at the canonical watermark, so retained history is never rescanned.
    registry = InMemoryCanonicalProjectionStore(store)
    publisher = CanonicalEventPublisher(store, legacy_bus=EventBus(), projection_registry=registry)
    await publisher.emit(_event("first-tracked"))
    await _tick(registry=registry, failures=failures, store=store, log=log, holder="r1")

    rows = await log.query(event_type="agent.recovery")
    assert [row.payload[CANONICAL_EVENT_METADATA]["event_id"] for row in rows] == ["first-tracked"]


async def test_a_poison_event_dead_letters_and_releases_its_stream() -> None:
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    registry = InMemoryCanonicalProjectionStore(store)
    failures = InMemoryProjectionFailureStore(max_attempts=2, retry_backoff_seconds=0.0)
    publisher = _publisher(
        store,
        log=log,
        registry=registry,
        fail_while=lambda kwargs: kwargs.get("source_event_id") == "poison-1",
    )

    with pytest.raises(EventSubscriberFailure):
        await publisher.emit(_event("poison-1"))
    await publisher.emit(_event("after-poison"))

    first = await _tick(registry=registry, failures=failures, store=store, log=log, holder="r1")
    assert first.projected == 0  # the poison holds the stream this tick

    second = await _tick(registry=registry, failures=failures, store=store, log=log, holder="r1")
    assert second.dead_lettered == 1
    assert second.projected == 1
    rows = await log.query(event_type="agent.recovery")
    assert [row.payload[CANONICAL_EVENT_METADATA]["event_id"] for row in rows] == ["after-poison"]

    dead = await failures.poisoned_records()
    assert len(dead) == 1
    assert dead[0].event_id == "poison-1"
    assert dead[0].stream_id == "workspace:workspace-2506"
    assert dead[0].attempts == 2
    # A later tick does not resurrect the disposition or re-project the row.
    third = await _tick(registry=registry, failures=failures, store=store, log=log, holder="r1")
    assert third.dead_lettered == 0
    assert len(await log.query(event_type="agent.recovery")) == 1


async def test_backoff_holds_the_stream_below_a_retryable_failure() -> None:
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    registry = InMemoryCanonicalProjectionStore(store)
    # Fail the bridge append and the projector's first attempt, succeed
    # afterwards: the recorded failure must hold the stream for exactly as
    # long as its backoff window runs.
    attempts: dict[str, int] = {}

    def fail_first(kwargs: Any) -> bool:
        source = str(kwargs.get("source_event_id"))
        attempts[source] = attempts.get(source, 0) + 1
        return attempts[source] < 3

    failures = InMemoryProjectionFailureStore(
        max_attempts=5, retry_backoff_seconds=50.0, clock=lambda: 100.0
    )
    publisher = _publisher(
        store,
        log=log,
        registry=registry,
        fail_while=fail_first,
    )
    with pytest.raises(EventSubscriberFailure):
        await publisher.emit(_event("backoff-1"))

    first = await project_canonical_events(
        projection_store=registry,
        event_store=store,
        event_log=log,
        failure_store=failures,
        append_kwargs=canonical_log_append_kwargs,
        holder="r1",
        clock=lambda: 100.0,
    )
    assert first.projected == 0
    failure = await failures.get("backoff-1")
    assert failure is not None
    assert failure.next_attempt_at == pytest.approx(150.0)

    # Inside the backoff window the attempt is not due; the stream stays held.
    second = await project_canonical_events(
        projection_store=registry,
        event_store=store,
        event_log=log,
        failure_store=failures,
        append_kwargs=canonical_log_append_kwargs,
        holder="r1",
        clock=lambda: 149.0,
    )
    assert second.projected == 0
    failure = await failures.get("backoff-1")
    assert failure is not None and failure.attempts == 1

    # Once the window elapses the next attempt runs, and success clears the
    # failure evidence.
    third = await project_canonical_events(
        projection_store=registry,
        event_store=store,
        event_log=log,
        failure_store=failures,
        append_kwargs=canonical_log_append_kwargs,
        holder="r1",
        clock=lambda: 151.0,
    )
    assert third.projected == 1
    assert await failures.get("backoff-1") is None
    assert len(await log.query(event_type="agent.recovery")) == 1


async def test_two_replicas_share_one_stream_lease_and_progress_after_expiry() -> None:
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    registry = InMemoryCanonicalProjectionStore(store)
    failures = InMemoryProjectionFailureStore(retry_backoff_seconds=0.0)
    publisher = _publisher(
        store,
        log=log,
        registry=registry,
        fail_while=_fail_first(1),
    )
    with pytest.raises(EventSubscriberFailure):
        await publisher.emit(_event("shared-1"))

    # Replica A holds a live lease; replica B's tick must not double-scan.
    lease = await registry.claim("workspace:workspace-2506", holder="a", lease_seconds=300.0)
    assert isinstance(lease, ProjectionLease)
    b_outcome = await _tick(registry=registry, failures=failures, store=store, log=log, holder="b")
    assert b_outcome.streams_scanned == 0
    assert await log.query(event_type="agent.recovery") == []

    # A's lease lapses; B takes the stream over and heals it. A's stale
    # fencing token can no longer move the cursor.
    expired = await registry.claim("workspace:workspace-2506", holder="a", lease_seconds=0.0)
    assert expired is not None
    taken = await registry.claim("workspace:workspace-2506", holder="b", lease_seconds=300.0)
    assert taken is not None and taken.fencing_token != expired.fencing_token
    assert not await registry.advance(
        "workspace:workspace-2506", fencing_token=expired.fencing_token, position=99
    )
    outcome = await _tick(registry=registry, failures=failures, store=store, log=log, holder="b")
    assert outcome.projected == 1
    assert len(await log.query(event_type="agent.recovery")) == 1


async def test_concurrent_projector_ticks_converge_on_one_row() -> None:
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    registry = InMemoryCanonicalProjectionStore(store)
    failures = InMemoryProjectionFailureStore(retry_backoff_seconds=0.0)
    publisher = _publisher(
        store,
        log=log,
        registry=registry,
        fail_while=_fail_first(1),
    )
    with pytest.raises(EventSubscriberFailure):
        await publisher.emit(_event("raced-1"))

    first, second = await asyncio.gather(
        _tick(registry=registry, failures=failures, store=store, log=log, holder="a"),
        _tick(registry=registry, failures=failures, store=store, log=log, holder="b"),
    )
    delivered = first.projected + second.projected
    assert delivered == 1
    assert len(await log.query(event_type="agent.recovery")) == 1


async def test_a_publisher_without_a_projection_registry_cannot_heal() -> None:
    """The bridge alone was the whole old story; it must stay insufficient.

    #2506's criterion: tests fail if the durable-log projector becomes solely
    ``if outcome.inserted: legacy_bus.emit(...)`` again. A publisher wired the
    old way — bus projection only, no registry, no projector scan — leaves
    the failed occurrence invisible no matter how many ticks run.
    """
    store = InMemoryEventStore()
    log = InMemoryEventLog()
    publisher = _publisher(store, log=log, registry=None)
    failures = InMemoryProjectionFailureStore()
    # The projector scans registered streams; none exist without the registry.
    empty_registry = InMemoryCanonicalProjectionStore(store)

    with pytest.raises(EventSubscriberFailure):
        await publisher.emit(_event("lost-without-registry"))
    for _ in range(3):
        await _tick(registry=empty_registry, failures=failures, store=store, log=log, holder="r1")

    assert await store.get("lost-without-registry") is not None
    assert await log.query(event_type="agent.recovery") == []


# --- SQLite backends -------------------------------------------------------


_SQLITE_EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_event_log (
    event_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT '',
    stream_scope TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    node_run_id TEXT NOT NULL DEFAULT '',
    attempt_id TEXT NOT NULL DEFAULT '',
    invocation_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL DEFAULT '',
    causation_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    provenance TEXT NOT NULL DEFAULT '{}',
    UNIQUE(stream_id, sequence)
);
CREATE TABLE IF NOT EXISTS canonical_event_stream_watermarks (
    stream_id TEXT PRIMARY KEY,
    last_sequence INTEGER NOT NULL
);
"""


@pytest.fixture
async def sqlite_conn():
    conn = await aiosqlite.connect(":memory:")
    try:
        await execute_schema_script(conn, _SQLITE_EVENT_SCHEMA)
        await conn.commit()
        yield conn
    finally:
        await conn.close()


async def test_sqlite_backends_project_and_dedupe_end_to_end(sqlite_conn) -> None:
    store = SqliteEventStore(sqlite_conn)
    log = SqliteEventLog(sqlite_conn)
    await log.ensure_schema()
    from maistro.events.processing import (
        SqliteCanonicalProjectionStore,
        SqliteProjectionFailureStore,
    )

    registry = SqliteCanonicalProjectionStore(sqlite_conn)
    failures = SqliteProjectionFailureStore(sqlite_conn, retry_backoff_seconds=0.0)
    await registry.ensure_schema()
    await failures.ensure_schema()

    publisher = CanonicalEventPublisher(store, legacy_bus=EventBus(), projection_registry=registry)
    await publisher.emit(_event("sqlite-1"))

    outcome = await project_canonical_events(
        projection_store=registry,
        event_store=store,
        event_log=log,
        failure_store=failures,
        append_kwargs=canonical_log_append_kwargs,
        holder="r1",
    )
    assert outcome.projected == 1
    rows = await log.query(event_type="agent.recovery")
    assert len(rows) == 1
    assert rows[0].payload[CANONICAL_EVENT_METADATA]["event_id"] == "sqlite-1"

    # The log's source-id dedupe: the projector rescan and a hypothetical
    # second bridge append both converge on the one row.
    again = await project_canonical_events(
        projection_store=registry,
        event_store=store,
        event_log=log,
        failure_store=failures,
        append_kwargs=canonical_log_append_kwargs,
        holder="r1",
    )
    assert again.projected == 0
    assert len(await log.query(event_type="agent.recovery")) == 1


async def test_sqlite_event_log_dedupe_returns_the_existing_row(sqlite_conn) -> None:
    log = SqliteEventLog(sqlite_conn)
    await log.ensure_schema()
    first = await log.append("agent.recovery", source_event_id="sqlite-dedupe")
    second = await log.append("agent.recovery", source_event_id="sqlite-dedupe")
    assert second.id == first.id
    assert len(await log.query(event_type="agent.recovery")) == 1
    # Unkeyed rows (the legacy bridge's non-canonical traffic) are untouched.
    await log.append("agent.recovery")
    await log.append("agent.recovery")
    assert len(await log.query(event_type="agent.recovery")) == 3


async def test_sqlite_projection_store_upgrades_a_preexisting_log(sqlite_conn) -> None:
    """A database created before #2506 gains the source column in place."""
    from maistro.sqlite_schema import serialized_schema_upgrade

    legacy = """
    CREATE TABLE IF NOT EXISTS event_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT '',
        entity_id TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL DEFAULT '{}',
        source TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL
    );
    """
    async with serialized_schema_upgrade(sqlite_conn):
        await execute_schema_script(sqlite_conn, legacy)
        await sqlite_conn.commit()
    log = SqliteEventLog(sqlite_conn)
    await log.ensure_schema()
    row = await log.append("agent.recovery", source_event_id="upgraded-1")
    assert row.id > 0
    again = await log.append("agent.recovery", source_event_id="upgraded-1")
    assert again.id == row.id


# --- Container wiring (in-memory) -----------------------------------------


async def test_container_heals_a_failed_bridge_append_through_the_ordinary_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The issue's first falsifiable scenario, in-memory backend.

    Force the durable-log append to throw after the canonical append commits:
    one canonical event, zero ADR-086 rows, no handler invocation and no
    success-shaped trigger claim — then the healed ordinary tick delivers
    exactly one log occurrence and one receipt referencing the original
    canonical identity and Workspace sequence.
    """
    from maistro.container import create_container
    from maistro.events.durable_log import InMemoryEventLog
    from maistro.events.invocations import ReplaySafety
    from maistro.types import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    try:
        delivered: list[tuple[str, dict[str, Any]]] = []

        async def recorder(_trigger: object, event: object) -> None:
            payload = getattr(event, "payload", {})
            delivered.append((getattr(event, "event_type", ""), dict(payload)))

        container.handler_caller = recorder
        await container.trigger_store.add(
            TriggerDefinition(
                trigger_id="t2506",
                name="on-recovery",
                event_pattern="agent.recovery",
                handler_url="http://handlers.invalid/recovery",
                replay_safety=ReplaySafety.IDEMPOTENT,
                contract_ref="contract-v1",
            )
        )

        bus_fired: list[str] = []

        async def bus_handler(_trigger: Trigger, event: Any) -> None:
            bus_fired.append(event.event_id)

        container.event_bus.register_handler("capture", bus_handler)
        container.event_bus.add_trigger(
            Trigger(
                name="capture",
                event_types=["agent.recovery"],
                action_type="capture",
                cooldown_seconds=0,
            )
        )

        original_append = InMemoryEventLog.append

        async def poisoned_append(self: InMemoryEventLog, event_type: str, **kwargs: Any) -> Any:
            if event_type == "agent.recovery":
                raise POISON
            return await original_append(self, event_type, **kwargs)

        monkeypatch.setattr(InMemoryEventLog, "append", poisoned_append)
        envelope = _event("container-2506")
        with pytest.raises(EventSubscriberFailure):
            await container.canonical_event_publisher.emit(envelope)

        # One canonical event, zero durable-log rows, no bus trigger fired,
        # no handler delivery — nothing claimed success.
        persisted = await container.capability_effects.event_store.get("container-2506")
        assert persisted is not None and persisted.sequence is not None
        assert await container.durable_event_log.query(event_type="agent.recovery") == []
        assert bus_fired == []
        assert delivered == []

        # Heal the durable log, then use only the ordinary production tick.
        monkeypatch.setattr(InMemoryEventLog, "append", original_append)
        cursor = await container.process_durable_events()
        assert cursor > 0

        rows = await container.durable_event_log.query(event_type="agent.recovery")
        assert len(rows) == 1
        metadata = rows[0].payload[CANONICAL_EVENT_METADATA]
        assert metadata["event_id"] == "container-2506"
        assert metadata["sequence"] == persisted.sequence
        assert metadata["workspace_id"] == "workspace-2506"

        receipts = await container.handler_invocation_store.list_for_event(rows[0].id)
        assert len(receipts) == 1
        assert receipts[0].trigger_id == "t2506"
        assert receipts[0].status.value in {"success", "failed", "unknown", "pending"}

        # Redelivery is idempotent: a second tick adds no row and no call.
        await container.process_durable_events()
        assert len(await container.durable_event_log.query(event_type="agent.recovery")) == 1
        assert len(delivered) == 1
    finally:
        monkeypatch.undo()
        await container.aclose()


async def test_container_projection_pass_runs_before_the_legacy_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One tick both heals and dispatches: the pass order is the contract."""
    from maistro.container import create_container
    from maistro.events.durable_log import InMemoryEventLog
    from maistro.events.invocations import ReplaySafety
    from maistro.types import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    try:
        delivered: list[str] = []

        async def recorder(_trigger: object, event: object) -> None:
            metadata = dict(event.payload).get(CANONICAL_EVENT_METADATA, {})
            delivered.append(str(metadata.get("event_id")))

        container.handler_caller = recorder
        await container.trigger_store.add(
            TriggerDefinition(
                trigger_id="t2506b",
                name="on-recovery",
                event_pattern="agent.recovery",
                handler_url="http://handlers.invalid/recovery",
                replay_safety=ReplaySafety.IDEMPOTENT,
                contract_ref="contract-v1",
            )
        )
        original_append = InMemoryEventLog.append

        async def poisoned_append(self: InMemoryEventLog, event_type: str, **kwargs: Any) -> Any:
            if event_type == "agent.recovery":
                raise POISON
            return await original_append(self, event_type, **kwargs)

        monkeypatch.setattr(InMemoryEventLog, "append", poisoned_append)
        with pytest.raises(EventSubscriberFailure):
            await container.canonical_event_publisher.emit(_event("same-tick-2506"))
        monkeypatch.setattr(InMemoryEventLog, "append", original_append)

        await container.process_durable_events()
        assert delivered == ["same-tick-2506"]
    finally:
        monkeypatch.undo()
        await container.aclose()
