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
