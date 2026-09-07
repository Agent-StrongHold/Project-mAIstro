"""DAG-run live state — in-memory ring buffer of recent runs + their events.

Hive DAG execution routes append node lifecycle events directly to this store.
Routes/dag_runs.py exposes list/get/SSE-stream over the resulting history.
The historical ``pm_node_*`` event names remain part of that presentation
contract, but the store no longer installs or owns a PM-specific executor bus.

Runs are grouped by the run id supplied by the executing route. Each run has
ordered node events; the frontend reconstructs the live DAG state from them.

Run records are durable: the store mirrors every mutation into
`stores.dag_runs`, the same `JsonStore` registry that already backs
missions, DAG definitions and dashboard layouts, so a run survives a
restart (#697).

**Restart durability, not live multi-replica freshness.** `JsonStore` is a
process cache filled once at `initialize()`; it does not read through on
every access, and neither does this store. A replica that starts after a
write sees it; a replica already running does not, until it reloads.
That is true of every family in `stores.py`, not a property of run
history, so the honest scope is stated here rather than claimed away --
`reload()` is the seam an operator or a future read-through has to use
(Codex, #697).

SSE subscribers are not, and cannot be. A subscriber is an
`asyncio.Queue` belonging to one open HTTP connection in one process;
there is nothing to persist and nothing another replica could do with
it. Only the record and its events are durable, which is what the
"Recent runs" list reads.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_RUNS = 100
MAX_EVENTS_PER_RUN = 200
MAX_SSE_QUEUE = 200
#: Longest response text kept in a stored run record, matching the cap the run
#: route already applies to the copy it puts in each event.
MAX_RESULT_CHARS = 2000

#: The budget across every node result in one run. `MAX_RESULT_CHARS` bounds
#: one node; a DAG may have any number of them, so without this the record is
#: unbounded in the dimension that actually grows. 50x the per-node cap: a run
#: whose first twenty-five nodes each produced a full-length answer has already
#: told a reader what happened, and the untruncated text of every node is in
#: that run's events under their own cap.
MAX_RESULT_CHARS_PER_RUN = 50 * MAX_RESULT_CHARS


def _bounded(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """A run result with its node responses truncated to `MAX_RESULT_CHARS`.

    Truncated rather than dropped: the outcome shape is what a reader of the
    history wants, and the full text is already in the run's events under the
    same cap.
    """
    if not result:
        return result
    node_results = result.get("node_results")
    if not isinstance(node_results, dict):
        return result
    trimmed = {}
    spent = 0
    for node_id, node in node_results.items():
        if isinstance(node, dict) and isinstance(node.get("response"), str):
            # Per node AND in total. `UpdateDAGBody.nodes` is an unconstrained
            # list, so a per-node cap alone bounds nothing: a 500-node DAG
            # still writes a megabyte per run, and the "bounded record"
            # guarantee this store documents would not have been enforced
            # (Codex, #703).
            room = max(0, min(MAX_RESULT_CHARS, MAX_RESULT_CHARS_PER_RUN - spent))
            response = node["response"][:room]
            spent += len(response)
            node = {**node, "response": response}
        trimmed[node_id] = node
    return {**result, "node_results": trimmed}


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
    dag_id: str = ""
    #: "running" until the run reports otherwise. Declared, because the run
    #: route used to assign `run.status` and `run.result` to a dataclass that
    #: had neither -- Python attached both silently and `to_summary` read
    #: neither, so a completed run never reported completion to the list
    #: endpoint (#697).
    status: str = "running"
    result: dict[str, Any] | None = None
    #: The canonical `Run` this execution is, when the caller has one.
    #:
    #: `POST /v1/dags/{id}/run` does not: it calls `execute_dag`, which mints
    #: no canonical Run at all, so the id here stays empty on that path. That
    #: convergence is #53's, not this change's -- the field exists so the run
    #: record has somewhere to carry the identity the moment the execution
    #: path produces one, rather than needing a schema change then.
    canonical_run_id: str = ""

    @classmethod
    def from_record(cls, raw: dict[str, Any]) -> DagRun:
        """Rebuild a run from its stored form."""
        return cls(
            id=raw["id"],
            started_at=raw["started_at"],
            user_id=raw.get("user_id", ""),
            events=[DagRunEvent(**ev) for ev in raw.get("events", [])],
            finished_at=raw.get("finished_at"),
            dag_id=raw.get("dag_id", ""),
            status=raw.get("status", "running"),
            result=raw.get("result"),
            canonical_run_id=raw.get("canonical_run_id", ""),
        )

    def to_record(self) -> dict[str, Any]:
        """The stored form: everything `from_record` needs, and nothing else.

        `result` is stored as a summary, not verbatim. `execute_dag` returns
        every node's full response, and the route already truncates the copy it
        puts in each event to `MAX_RESULT_CHARS` -- so persisting the raw result
        would grow the SQLite state without bound and retain more output than
        the history API ever exposes (Codex, #697).
        """
        return {
            "id": self.id,
            "started_at": self.started_at,
            "user_id": self.user_id,
            "finished_at": self.finished_at,
            "dag_id": self.dag_id,
            "status": self.status,
            "result": _bounded(self.result),
            "canonical_run_id": self.canonical_run_id,
            "events": [asdict(ev) for ev in self.events],
        }

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
            "dag_id": self.dag_id,
            "status": self.status,
            "canonical_run_id": self.canonical_run_id,
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
    """DAG runs, durable when given a records store, plus per-run SSE subscribers.

    `records` is the `JsonStore` the run history is written to. Passing `None`
    keeps the pre-#697 behaviour -- history lives only in this process and is
    lost on restart -- which is what the tests and a Conductor started without
    persistence get. `load()` is what brings a restarted process back.
    """

    def __init__(self, *, max_runs: int = MAX_RUNS, records: Any | None = None) -> None:
        self._runs: dict[str, DagRun] = {}
        self._order: deque[str] = deque(maxlen=max_runs)
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._records = records
        if records is not None:
            self.load()

    @property
    def is_durable(self) -> bool:
        """Whether history written here outlives the process.

        Read by the list endpoint so the API can say which it is, rather than
        presenting a volatile buffer and a durable history identically (#333).
        """
        return self._records is not None

    def reload(self) -> None:
        """Re-read the records store, refreshing its own cache first.

        The refresh is the whole point and it was missing: `JsonStore.values()`
        returns `_data`, which is filled from persistence once by
        `initialize()` and never read through again, so a `reload()` that only
        re-walked `values()` re-processed this replica's own cache and could
        not see another replica's write at all (Codex, #703). `initialize()` is
        the JsonStore's read-through, so it runs first.

        Public because the freshness limit above is real: this store caches, so
        a process that was already running when another wrote does not see the
        write until it reloads.
        """
        records = self._records
        refresh = getattr(records, "initialize", None)
        if callable(refresh):
            refresh()
        self.load()

    def load(self) -> None:
        """Rehydrate the working set from the records store, newest last.

        Ordering is restored from `started_at` rather than from whatever order
        the store iterates in: `_order` is a bounded deque and the eviction it
        drives has to drop the *oldest* run, which a dict's insertion order
        would not reliably give back after a reload.
        """
        if self._records is None:
            return
        runs = [DagRun.from_record(raw) for raw in self._records.values()]
        runs.sort(key=lambda r: r.started_at)
        keep = runs[-self._order.maxlen :] if self._order.maxlen else runs
        # The rows that did not survive the bound go too. A store holding more
        # than `max_runs` -- after the bound is lowered, say -- would otherwise
        # keep them forever: dropped from the working set on every load, never
        # deleted, and permanently above the retention the API advertises
        # (Codex, #697).
        kept = {run.id for run in keep}
        for run in runs:
            if run.id not in kept:
                self._forget(run.id)
        self._runs = {run.id: run for run in keep}
        self._order = deque((run.id for run in keep), maxlen=self._order.maxlen)

    def _persist(self, run: DagRun) -> None:
        if self._records is not None:
            self._records[run.id] = run.to_record()

    def _forget(self, run_id: str) -> None:
        if self._records is not None:
            self._records.pop(run_id, None)

    async def start_run(
        self,
        *,
        user_id: str = "",
        run_id: str | None = None,
        dag_id: str = "",
        canonical_run_id: str = "",
    ) -> DagRun:
        """Begin a new run (correlation key). Returns the DagRun object.

        Evicts the oldest run from `_runs` dict + `_subscribers` map when the
        ring buffer is full. The deque itself silently drops the oldest entry
        when maxlen is exceeded; we mirror that by removing from the dict
        BEFORE the deque autoshifts so subscribers + run records stay in sync.
        """
        rid = run_id or uuid.uuid4().hex[:12]
        run = DagRun(
            id=rid,
            started_at=time.time(),
            user_id=user_id,
            dag_id=dag_id,
            canonical_run_id=canonical_run_id,
        )
        async with self._lock:
            # If we're at capacity, manually evict before append (otherwise
            # the deque drops eldest silently and our dict grows unbounded).
            if self._order.maxlen is not None and len(self._order) >= self._order.maxlen:
                stale = self._order.popleft()
                self._runs.pop(stale, None)
                self._subscribers.pop(stale, None)
                # The record goes with it. A row outliving the working set
                # would come back on the next `load()` and re-expand history
                # past the bound the deque exists to hold.
                self._forget(stale)
            self._runs[rid] = run
            self._order.append(rid)
        self._persist(run)
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
            self._persist(run)
        # Fan out to SSE subscribers.
        for q in self._subscribers.get(run_id, []):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)
        return ev

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str = "completed",
        result: dict[str, Any] | None = None,
    ) -> None:
        """Mark a run finished, with the outcome it finished with.

        `status` and `result` are parameters rather than attributes the caller
        assigns, which is the defect this closes: the run route set
        `run.status` and `run.result` on a dataclass declaring neither, so
        Python attached them, `to_summary` never read them, and a completed run
        reported nothing to the list endpoint (#697).
        """
        run = self._runs.get(run_id)
        if run and run.finished_at is None:
            run.finished_at = time.time()
            run.status = status
            if result is not None:
                run.result = result
            self._persist(run)

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


def configure_dag_run_store(records: Any) -> DagRunStore:
    """Rebuild the process store on a durable records store, and load it.

    Called from Conductor startup once `stores.configure_persistence` has run.
    This store had no setter at all before -- not even the unused kind the
    other families carry -- so there was no seam through which durability
    could arrive (#697).
    """
    global _global_store
    _global_store = DagRunStore(records=records)
    return _global_store
