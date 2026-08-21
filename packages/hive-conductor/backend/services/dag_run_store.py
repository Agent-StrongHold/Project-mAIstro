"""DAG-run live state — in-memory ring buffer of recent runs + their events.

Day 6 v0 deliverable. Hive backend subscribes to maistro's EventBus
(via maistro.agents.pm_runner's _pm_event_bus hook). Every pm_node_*
event becomes part of a "run" record. Routes/dag_runs.py exposes
list/get/SSE-stream over this store.

Runs are grouped by `correlation_id` (set by pm_fleet.invoke_pm_agent
in v0.5; for now we group by the program_pulse session). Each run has
ordered node events; the frontend reconstructs the live DAG state from
them.

v0.5 persists to postgres; v0 in-memory is sufficient for the live
demo loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

MAX_RUNS = 100
MAX_EVENTS_PER_RUN = 200
MAX_SSE_QUEUE = 200


@dataclass
class DagRunEvent:
    run_id: str
    event_type: str  # pm_node_started | pm_node_completed | pm_node_failed
    role: str  # e.g. "intake", "delivery"
    capability: str  # e.g. "create_initiative", "poll_jira"
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class DagRun:
    id: str
    started_at: float
    user_id: str = ""
    events: list[DagRunEvent] = field(default_factory=list)
    finished_at: float | None = None

    def to_summary(self) -> dict[str, Any]:
        nodes_seen: dict[str, str] = {}
        for ev in self.events:
            key = f"{ev.role}.{ev.capability}"
            if ev.event_type == "pm_node_completed":
                nodes_seen[key] = ev.payload.get("source", "llm")
            elif ev.event_type == "pm_node_failed":
                nodes_seen[key] = "failed"
            elif key not in nodes_seen:
                nodes_seen[key] = "running"
        return {
            "id": self.id,
            "user_id": self.user_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "event_count": len(self.events),
            "node_states": nodes_seen,
        }

    def to_detail(self) -> dict[str, Any]:
        return {
            **self.to_summary(),
            "events": [
                {
                    "event_type": ev.event_type,
                    "role": ev.role,
                    "capability": ev.capability,
                    "payload": ev.payload,
                    "timestamp": ev.timestamp,
                }
                for ev in self.events
            ],
        }


class DagRunStore:
    """In-memory store of DAG runs + per-run SSE subscribers."""

    def __init__(self, *, max_runs: int = MAX_RUNS) -> None:
        self._runs: dict[str, DagRun] = {}
        self._order: deque[str] = deque(maxlen=max_runs)
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def start_run(self, *, user_id: str = "", run_id: str | None = None) -> DagRun:
        """Begin a new run (correlation key). Returns the DagRun object.

        Evicts the oldest run from `_runs` dict + `_subscribers` map when the
        ring buffer is full. The deque itself silently drops the oldest entry
        when maxlen is exceeded; we mirror that by removing from the dict
        BEFORE the deque autoshifts so subscribers + run records stay in sync.
        """
        rid = run_id or uuid.uuid4().hex[:12]
        run = DagRun(id=rid, started_at=time.time(), user_id=user_id)
        async with self._lock:
            # If we're at capacity, manually evict before append (otherwise
            # the deque drops eldest silently and our dict grows unbounded).
            if self._order.maxlen is not None and len(self._order) >= self._order.maxlen:
                stale = self._order.popleft()
                self._runs.pop(stale, None)
                self._subscribers.pop(stale, None)
            self._runs[rid] = run
            self._order.append(rid)
        return run

    async def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        role: str,
        capability: str,
        payload: dict[str, Any] | None = None,
    ) -> DagRunEvent:
        ev = DagRunEvent(
            run_id=run_id,
            event_type=event_type,
            role=role,
            capability=capability,
            payload=payload or {},
        )
        run = self._runs.get(run_id)
        if run is not None:
            run.events.append(ev)
            if len(run.events) > MAX_EVENTS_PER_RUN:
                run.events = run.events[-MAX_EVENTS_PER_RUN:]
        # Fan out to SSE subscribers.
        for q in self._subscribers.get(run_id, []):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)
        return ev

    async def finish_run(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run and run.finished_at is None:
            run.finished_at = time.time()

    def list_runs(self, *, limit: int = 25) -> list[dict[str, Any]]:
        recent = list(self._order)[-limit:]
        return [self._runs[rid].to_summary() for rid in reversed(recent) if rid in self._runs]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self._runs.get(run_id)
        return run.to_detail() if run else None

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_SSE_QUEUE)
        self._subscribers[run_id].append(q)
        # Replay buffered events so a late subscriber doesn't miss the start.
        run = self._runs.get(run_id)
        if run is not None:
            for ev in run.events:
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    break
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id, [])
        if q in subs:
            subs.remove(q)
        if not subs and run_id in self._subscribers:
            del self._subscribers[run_id]


_global_store: DagRunStore | None = None


def get_dag_run_store() -> DagRunStore:
    global _global_store
    if _global_store is None:
        _global_store = DagRunStore()
    return _global_store


# -------------------------------------------------------------------------
# pm_runner event bridge — Hive startup calls install_pm_event_bridge() to
# subscribe to maistro's pm_node_* events and write them to the store.
# -------------------------------------------------------------------------


def install_pm_event_bridge(
    *,
    store: DagRunStore | None = None,
    current_run_id_provider=None,
) -> None:
    """Wire pm_runner's _pm_event_bus → DagRunStore.

    `current_run_id_provider` is an optional callable returning the active
    run id (e.g. derived from request context or program-pulse session).
    If None, every event creates its own ephemeral run (v0 fallback).
    """
    from maistro.agents import pm_runner
    from maistro.events.bus import Event

    store = store or get_dag_run_store()

    async def _on_event(trigger, event: Event) -> None:  # bus action_handler signature
        run_id = current_run_id_provider() if current_run_id_provider else None
        if not run_id:
            # No active run — create an ephemeral one so events aren't dropped.
            run = await store.start_run()
            run_id = run.id
        await store.append_event(
            run_id,
            event_type=event.event_type,
            role=event.payload.get("role", ""),
            capability=event.payload.get("capability", ""),
            payload=dict(event.payload),
        )
        if event.event_type in {"pm_node_completed", "pm_node_failed"}:
            # Only mark finished when the LAST node of a run completes — v0
            # doesn't track total node count, so we leave finished_at None
            # and rely on a separate program_pulse-completion signal.
            pass

    # Create + bind an EventBus instance, then wire pm_runner's hook.
    from maistro.events.bus import EventBus, Trigger

    bus = EventBus()
    trigger = Trigger(
        name="pm-events-to-dag-store",
        event_types=["pm_node_started", "pm_node_completed", "pm_node_failed"],
        action_type="dag_store",
    )
    bus.add_trigger(trigger)
    bus.register_handler("dag_store", _on_event)
    pm_runner.set_pm_event_bus(bus)
