"""Contract tests for the canonical event envelope and persistence stores."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.events.envelope import (
    MAX_EVENT_FIELD_BYTES,
    MAX_EVENT_FIELD_DEPTH,
    EventEnvelope,
    EventPayloadTooLarge,
    EventStore,
    InMemoryEventStore,
    SqliteEventStore,
)


def _encoded_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _payload_of_exact_size(n_bytes: int) -> dict:
    """Build a JSON-compact payload whose encoded size is exactly `n_bytes`.

    Computed directly from the empty-filler overhead rather than growing the
    filler one character at a time, which would re-serialize the whole string
    on every step -- quadratic, and unusably slow at a 256 KiB target.
    """
    overhead = _encoded_size({"d": ""})
    filler_len = n_bytes - overhead
    assert filler_len >= 0, f"{n_bytes} bytes is smaller than the empty-filler overhead {overhead}"
    payload = {"d": "x" * filler_len}
    assert _encoded_size(payload) == n_bytes, "target size unreachable with this filler"
    return payload


def _nested_dict(depth: int) -> dict:
    """Build a dict nesting exactly `depth` levels deep (a bare `{}` is depth 1)."""
    value: dict = {}
    for _ in range(depth - 1):
        value = {"inner": value}
    return value


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[EventStore]:
    if request.param == "memory":
        yield InMemoryEventStore()
        return

    conn = await aiosqlite.connect(":memory:")
    sqlite_store = SqliteEventStore(conn)
    await sqlite_store.ensure_schema()
    yield sqlite_store
    await conn.close()


def test_envelope_preserves_canonical_correlation_fields() -> None:
    event = EventEnvelope(
        type="attempt.completed",
        payload={"result": {"ok": True}},
        workspace_id="ws-1",
        project_id="project-1",
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        invocation_id="inv-3",
        session_id="session-1",
        correlation_id="corr-1",
        causation_id="event-parent",
        source="execution-runtime",
        actor_id="agent-1",
        provenance={"provider": "local"},
    )

    serialized = event.to_dict()
    assert serialized["type"] == "attempt.completed"
    assert serialized["payload"] == {"result": {"ok": True}}
    assert serialized["workspace_id"] == "ws-1"
    assert serialized["project_id"] == "project-1"
    assert serialized["run_id"] == "run-1"
    assert serialized["node_run_id"] == "node-run-1"
    assert serialized["attempt_id"] == "attempt-2"
    assert serialized["invocation_id"] == "inv-3"
    assert serialized["session_id"] == "session-1"
    assert serialized["correlation_id"] == "corr-1"
    assert serialized["causation_id"] == "event-parent"
    assert serialized["source"] == "execution-runtime"
    assert serialized["actor_id"] == "agent-1"
    assert serialized["provenance"] == {"provider": "local"}
    assert event.sequence is None


def test_workspace_defines_canonical_stream() -> None:
    event = EventEnvelope(type="x", workspace_id="w1", run_id="r1")
    assert event.stream_id == "workspace:w1"


def test_non_workspace_event_requires_explicit_scope() -> None:
    with pytest.raises(ValueError, match="stream_scope"):
        EventEnvelope(type="x")

    event = EventEnvelope(type="system.health", stream_scope="system")
    assert event.stream_id == "scope:system"


def test_workspace_event_rejects_competing_scope() -> None:
    with pytest.raises(ValueError, match="competing"):
        EventEnvelope(type="x", workspace_id="w1", stream_scope="system")


class TestPayloadStructuralBounds:
    """#1164: payload/provenance are bounded before any backend sees them."""

    def test_a_payload_at_exactly_the_byte_ceiling_is_accepted(self) -> None:
        payload = _payload_of_exact_size(MAX_EVENT_FIELD_BYTES)
        event = EventEnvelope(type="x", workspace_id="w1", payload=payload)
        assert event.payload == payload

    def test_a_payload_one_byte_over_the_ceiling_is_rejected(self) -> None:
        payload = _payload_of_exact_size(MAX_EVENT_FIELD_BYTES + 1)
        with pytest.raises(EventPayloadTooLarge, match="payload") as excinfo:
            EventEnvelope(type="x", workspace_id="w1", payload=payload)
        assert excinfo.value.field == "payload"

    def test_a_large_string_value_counts_toward_the_byte_ceiling(self) -> None:
        payload = {"blob": "x" * (MAX_EVENT_FIELD_BYTES + 1)}
        with pytest.raises(EventPayloadTooLarge):
            EventEnvelope(type="x", workspace_id="w1", payload=payload)

    def test_a_large_array_counts_toward_the_byte_ceiling(self) -> None:
        payload = {"items": list(range(MAX_EVENT_FIELD_BYTES))}
        with pytest.raises(EventPayloadTooLarge):
            EventEnvelope(type="x", workspace_id="w1", payload=payload)

    def test_provenance_is_bounded_the_same_way_as_payload(self) -> None:
        provenance = _payload_of_exact_size(MAX_EVENT_FIELD_BYTES + 1)
        with pytest.raises(EventPayloadTooLarge, match="provenance") as excinfo:
            EventEnvelope(type="x", workspace_id="w1", provenance=provenance)
        assert excinfo.value.field == "provenance"

    def test_nesting_at_exactly_the_depth_ceiling_is_accepted(self) -> None:
        payload = _nested_dict(MAX_EVENT_FIELD_DEPTH)
        event = EventEnvelope(type="x", workspace_id="w1", payload=payload)
        assert event.payload == payload

    def test_nesting_one_level_past_the_depth_ceiling_is_rejected(self) -> None:
        payload = _nested_dict(MAX_EVENT_FIELD_DEPTH + 1)
        with pytest.raises(EventPayloadTooLarge, match="nests"):
            EventEnvelope(type="x", workspace_id="w1", payload=payload)

    def test_a_deeply_nested_payload_is_rejected_without_a_stack_overflow(self) -> None:
        """The depth check must be iterative: a pathological payload must fail
        cleanly rather than exhaust the interpreter's recursion limit first."""
        payload = _nested_dict(5000)
        with pytest.raises(EventPayloadTooLarge, match="nests"):
            EventEnvelope(type="x", workspace_id="w1", payload=payload)

    def test_a_non_json_encodable_payload_is_rejected_before_any_backend_sees_it(self) -> None:
        with pytest.raises(EventPayloadTooLarge, match="not JSON-encodable"):
            EventEnvelope(type="x", workspace_id="w1", payload={"bad": object()})

    async def test_the_bound_is_enforced_before_a_store_ever_receives_the_event(
        self, store: EventStore
    ) -> None:
        oversized = _payload_of_exact_size(MAX_EVENT_FIELD_BYTES + 1)
        with pytest.raises(EventPayloadTooLarge):
            await store.append(EventEnvelope(type="x", workspace_id="w1", payload=oversized))


class TestEventStoreContract:
    async def test_assigns_sequence_across_runs_in_workspace(self, store: EventStore) -> None:
        first = await store.append(
            EventEnvelope(type="run.started", workspace_id="ws-1", run_id="run-1")
        )
        second = await store.append(
            EventEnvelope(type="run.started", workspace_id="ws-1", run_id="run-2")
        )
        third = await store.append(
            EventEnvelope(type="node.started", workspace_id="ws-1", run_id="run-1")
        )

        assert first.sequence == 1
        assert second.sequence == 2
        assert third.sequence == 3

    async def test_workspace_sequences_are_independent(self, store: EventStore) -> None:
        workspace_a = await store.append(EventEnvelope(type="x", workspace_id="a"))
        workspace_b = await store.append(EventEnvelope(type="x", workspace_id="b"))
        workspace_a_2 = await store.append(EventEnvelope(type="y", workspace_id="a"))

        assert workspace_a.sequence == 1
        assert workspace_b.sequence == 1
        assert workspace_a_2.sequence == 2

    async def test_append_is_idempotent(self, store: EventStore) -> None:
        event = EventEnvelope(
            type="node.completed",
            workspace_id="ws-1",
            run_id="r1",
            event_id="stable",
        )
        first = await store.append(event)
        duplicate = await store.append(event)
        history = await store.list_stream("workspace:ws-1")

        assert duplicate == first
        assert [item.event_id for item in history] == ["stable"]

    async def test_rejects_caller_sequence(self, store: EventStore) -> None:
        event = EventEnvelope(type="x", workspace_id="ws-1", sequence=99)
        with pytest.raises(ValueError, match="store-assigned"):
            await store.append(event)

    async def test_round_trips_payload(self, store: EventStore) -> None:
        event = EventEnvelope(
            type="invocation.completed",
            workspace_id="ws-1",
            run_id="r1",
            attempt_id="a1",
            payload={"nested": [1, {"ok": True}]},
            provenance={"model": "example"},
        )
        persisted = await store.append(event)
        loaded = await store.get(persisted.event_id)

        assert loaded == persisted

    async def test_stream_cursor_supports_reconnect(self, store: EventStore) -> None:
        for index in range(5):
            event = EventEnvelope(type=f"event.{index}", workspace_id="ws-1", run_id="r1")
            await store.append(event)

        page = await store.list_stream("workspace:ws-1", after_sequence=2, limit=2)
        assert [event.sequence for event in page] == [3, 4]
        assert [event.type for event in page] == ["event.2", "event.3"]
        assert await store.list_stream("workspace:ws-1", limit=0) == []

    async def test_concurrent_producers_share_workspace_sequence(self, store: EventStore) -> None:
        events = [
            EventEnvelope(
                type="node.progress",
                workspace_id="ws-1",
                run_id=f"run-{index % 4}",
            )
            for index in range(25)
        ]
        persisted = await asyncio.gather(*(store.append(event) for event in events))
        sequences = [event.sequence for event in persisted]

        assert all(sequence is not None for sequence in sequences)
        assert sorted(sequence for sequence in sequences if sequence is not None) == list(
            range(1, 26)
        )

    async def test_retries_share_workspace_history(self, store: EventStore) -> None:
        first_attempt = EventEnvelope(
            type="attempt.failed",
            workspace_id="ws-1",
            run_id="r1",
            attempt_id="attempt-1",
        )
        second_attempt = EventEnvelope(
            type="attempt.started",
            workspace_id="ws-1",
            run_id="r1",
            attempt_id="attempt-2",
        )
        failed = await store.append(first_attempt)
        retried = await store.append(second_attempt)
        history = await store.list_stream("workspace:ws-1")

        assert failed.sequence == 1
        assert retried.sequence == 2
        assert [event.attempt_id for event in history] == ["attempt-1", "attempt-2"]
