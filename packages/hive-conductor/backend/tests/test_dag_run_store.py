"""Tests for the Day 6 DAG-run store + SSE event bridge.

The store is an in-memory ring buffer that pm_runner's events feed
into via maistro.events.bus → install_pm_event_bridge(). SSE subscribers
consume via store.subscribe(run_id).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# The hive-conductor backend isn't a proper package — main.py + routes/
# + services/ live at the package root. Add the backend dir to sys.path.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.dag_run_store import DagRunStore, get_dag_run_store  # noqa: E402


@pytest.mark.asyncio
async def test_start_run_returns_run_with_id():
    store = DagRunStore()
    run = await store.start_run(user_id="alice")
    assert run.id
    assert run.user_id == "alice"
    assert run.finished_at is None
    assert run.events == []


@pytest.mark.asyncio
async def test_list_runs_returns_most_recent_first():
    store = DagRunStore(max_runs=10)
    a = await store.start_run()
    b = await store.start_run()
    c = await store.start_run()
    listed = store.list_runs()
    listed_ids = [r["id"] for r in listed]
    # Most recent first: c, b, a
    assert listed_ids == [c.id, b.id, a.id]


@pytest.mark.asyncio
async def test_append_event_records_into_run():
    store = DagRunStore()
    run = await store.start_run()
    await store.append_event(
        run.id,
        event_type="pm_node_started",
        role="intake",
        capability="create_initiative",
    )
    await store.append_event(
        run.id,
        event_type="pm_node_completed",
        role="intake",
        capability="create_initiative",
        payload={"source": "llm", "duration_ms": 1234},
    )
    detail = store.get_run(run.id)
    assert detail is not None
    assert len(detail["events"]) == 2
    assert detail["events"][1]["payload"]["source"] == "llm"
    # node_states summary picks up the latest event for each (role.capability) pair.
    assert detail["node_states"]["intake.create_initiative"] == "llm"


@pytest.mark.asyncio
async def test_get_run_returns_none_for_unknown_id():
    store = DagRunStore()
    assert store.get_run("does-not-exist") is None


@pytest.mark.asyncio
async def test_ring_buffer_evicts_eldest_run_when_full():
    store = DagRunStore(max_runs=3)
    runs = []
    for _ in range(5):
        runs.append(await store.start_run())
    # First two runs should have been evicted; the last three remain.
    assert store.get_run(runs[0].id) is None
    assert store.get_run(runs[1].id) is None
    assert store.get_run(runs[2].id) is not None
    assert store.get_run(runs[3].id) is not None
    assert store.get_run(runs[4].id) is not None


@pytest.mark.asyncio
async def test_subscribe_replays_buffered_events_to_late_subscriber():
    """A subscriber that joins AFTER events were appended must still see
    them (so a late-arriving UI catches up to the live state)."""
    store = DagRunStore()
    run = await store.start_run()
    await store.append_event(
        run.id,
        event_type="pm_node_started",
        role="intake",
        capability="create_initiative",
    )
    await store.append_event(
        run.id,
        event_type="pm_node_completed",
        role="intake",
        capability="create_initiative",
        payload={"source": "llm"},
    )
    # Late subscriber arrives now
    q = store.subscribe(run.id)
    # Should receive both buffered events immediately (queue has size 2).
    e1 = await asyncio.wait_for(q.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q.get(), timeout=1.0)
    assert e1.event_type == "pm_node_started"
    assert e2.event_type == "pm_node_completed"
    store.unsubscribe(run.id, q)


@pytest.mark.asyncio
async def test_subscribe_receives_new_events_after_subscribe():
    store = DagRunStore()
    run = await store.start_run()
    q = store.subscribe(run.id)
    # Append AFTER subscribing — must arrive via queue.
    await store.append_event(
        run.id,
        event_type="pm_node_started",
        role="delivery",
        capability="poll_jira",
    )
    ev = await asyncio.wait_for(q.get(), timeout=1.0)
    assert ev.event_type == "pm_node_started"
    assert ev.role == "delivery"
    store.unsubscribe(run.id, q)


@pytest.mark.asyncio
async def test_finish_run_sets_finished_at():
    store = DagRunStore()
    run = await store.start_run()
    assert run.finished_at is None
    await store.finish_run(run.id)
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_singleton_get_dag_run_store_returns_same_instance():
    a = get_dag_run_store()
    b = get_dag_run_store()
    assert a is b


# --- canonical event sequence identity (#1183) --------------------------


@pytest.mark.asyncio
async def test_append_event_assigns_monotonic_per_run_seq():
    """Every event carries its 1-based position in the run's TOTAL history.

    The counter must not come from `len(events)`: the buffer is trimmed to
    `MAX_EVENTS_PER_RUN`, so only a dedicated counter survives trims and can
    serve as a gap-detecting cursor.
    """
    from services.dag_run_store import MAX_EVENTS_PER_RUN

    store = DagRunStore()
    run = await store.start_run(run_id="seq-1")
    for index in range(MAX_EVENTS_PER_RUN + 7):
        ev = await store.append_event(
            run.id, event_type="pm_node_started", role="intake", capability="c"
        )
        assert ev.seq == index + 1
    # The buffer trimmed; the counter did not.
    assert len(run.events) == MAX_EVENTS_PER_RUN
    assert run.event_seq == MAX_EVENTS_PER_RUN + 7
    detail = store.get_run(run.id)
    assert detail["events"][-1]["seq"] == MAX_EVENTS_PER_RUN + 7


@pytest.mark.asyncio
async def test_event_seq_survives_record_round_trip():
    """The counter is durable state: a reloaded store continues the sequence
    instead of re-numbering history from one."""
    from services.dag_run_store import DagRunStore

    class _Records(dict):
        def initialize(self) -> None: ...

    records = _Records()
    first = DagRunStore(records=records)
    await first.start_run(run_id="seq-durable")
    for _ in range(3):
        await first.append_event(
            "seq-durable", event_type="pm_node_started", role="a", capability="b"
        )

    reloaded = DagRunStore(records=records)
    ev = await reloaded.append_event(
        "seq-durable", event_type="pm_node_completed", role="a", capability="b"
    )
    assert ev.seq == 4


@pytest.mark.asyncio
async def test_slow_subscriber_overflow_is_detectable_not_silent():
    """#1183: a full bounded subscriber queue drops events, but the seqs make
    the loss visible. Delivered events stay contiguous; the run's durable
    history keeps every seq, so a reconnecting consumer can tell exactly what
    it missed instead of believing a contiguous stream that wasn't."""
    from services.dag_run_store import MAX_SSE_QUEUE

    store = DagRunStore()
    run = await store.start_run(run_id="seq-gap")
    q = store.subscribe(run.id)

    total = MAX_SSE_QUEUE + 5
    for _ in range(total):
        await store.append_event("seq-gap", event_type="pm_node_started", role="a", capability="b")

    # The slow consumer drains at its own pace: it gets the first MAX_SSE_QUEUE
    # events, contiguously.
    delivered = [await asyncio.wait_for(q.get(), timeout=1.0) for _ in range(MAX_SSE_QUEUE)]
    assert [ev.seq for ev in delivered] == list(range(1, MAX_SSE_QUEUE + 1))
    # Nothing more will arrive on this queue: the last five were dropped.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.05)
    store.unsubscribe(run.id, q)

    # Durable truth kept the whole sequence (bounded to the last
    # MAX_EVENTS_PER_RUN): a fresh subscriber replays a window that begins
    # PAST seq 1 — the discontinuity a resync marker announces.
    fresh = store.subscribe(run.id)
    first = await asyncio.wait_for(fresh.get(), timeout=1.0)
    assert first.seq > 1
    store.unsubscribe(run.id, fresh)
