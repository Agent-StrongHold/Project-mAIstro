"""M8-A7 (#887) research harness: concurrency invariants against real PostgreSQL.

The epic's hypothesis (#880): process-local asyncio locks and ordinary
integration tests cannot establish distributed invariants across multiple
workers; concurrent transactions against real PostgreSQL can expose races in
claims, idempotency, ordering, and terminal-state transitions.

What "multiple workers" means here, and why it is enough
--------------------------------------------------------
Each actor in these races is a real OS thread running its **own** asyncio
event loop over its **own** ``asyncpg`` pool -- so every actor's statements
run on a separate database session (separate backend, separate snapshot,
separate locks). That is the unit PostgreSQL actually serializes on; none of
the guards under test (row locks, unique indexes, single-statement upserts)
depend on process identity, so session independence is the property the
invariants need, and threads-with-own-loops provide it without paying
interpreter startup per actor. The existing races
(``test_pg_admission.py``, ``test_consumer_claim_recovery.py``) share one
pool on one loop, which cannot prove that a claim's lock waits on a
*different backend's* transaction; the harness below can, and does.

Self-validating contention (the race must have raced)
-----------------------------------------------------
A race test that accidentally serializes passes vacuously. Where post-hoc
outcomes cannot distinguish contention from serialization, the harness
proves contention structurally:

- the consumer-claim race holds the Run row lock on an independent
  connection and requires ``pg_blocking_pids`` to name every actor backend
  before releasing it -- a liveness poll, not a timing bound;
- the event-ordering race requires the per-actor id sets to interleave,
  which per-session serial execution cannot produce;
- the effect-claim race inserts a ``threading.Barrier`` between the
  read-none SELECT and the INSERT, making the read-none/read-none/insert
  window deterministic rather than probabilistic.

Targets (from the issue) and the invariants each race pins
----------------------------------------------------------
- Run/Attempt stores: duplicate consumer claims -> exactly one physical
  winner; dueling terminalizations -> one winner, legal final state; stale
  attempt COMPLETED under a terminal Run -> refused (#1335); no new
  NodeRun under a terminal Run.
- Invocation/effect stores: ``claim_run_by_effect`` survives a deliberate
  read-none/read-none/insert window; ``PgInvocationStore.claim`` dispatches
  a (trigger, event) exactly once across sessions and never re-claims a
  terminal invocation.
- Durable event ordering: concurrent appends from independent sessions
  yield unique ids in one total order.
- Recovery leases: ``PgConsumerCursorStore`` fencing -- a stale holder's
  advance is refused after re-claim, and position never moves backwards.

This module is research evidence for the #887 disposition note
(``docs/research/887-postgresql-concurrency-race-harness.md``), not
production code: it adds no product surface, and every invariant it pins was
already documented as designed behavior -- finding zero new races here is a
result about the guards, recorded in the note.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

asyncpg = pytest.importorskip("asyncpg")

from maistro.events.invocations import HandlerInvocation, InvocationStatus  # noqa: E402
from maistro.events.pg_stores import (  # noqa: E402
    PgConsumerCursorStore,
    PgEventLog,
    PgInvocationStore,
    PgTriggerStore,
)
from maistro.events.trigger_store import TriggerDefinition  # noqa: E402
from maistro.graph import Graph, Node  # noqa: E402
from maistro.persistence import _register_json_codecs  # noqa: E402
from maistro.projects.pg_scope_store import PgProjectScopeStore  # noqa: E402
from maistro.runs.consumer_claim import ClaimingPgRunStore, ConsumerClaimLost  # noqa: E402
from maistro.runs.lifecycle import InvalidLifecycleTransition  # noqa: E402
from maistro.runs.model import AttemptStatus, RunStatus  # noqa: E402
from maistro.runs.pg_store import PgRunStore  # noqa: E402
from maistro.runs.store import RunIntegrityError  # noqa: E402
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID  # noqa: E402
from maistro.testing.postgres import postgres_dsn  # noqa: E402

#: Actors per race. Four independent sessions are enough to prove the
#: guards; more only lengthens pool setup.
ACTORS = 4

#: Liveness budget for the ``pg_blocking_pids`` contention witness. This is
#: a wait-for (the blocked condition is *guaranteed* while the harness holds
#: the row lock), not a timing assertion about the code under test.
CONTENTION_TIMEOUT_S = 30.0

EVENTS_PER_ACTOR = 25

CLAIM_LEASE = timedelta(seconds=30)


@pytest.fixture
def pg_dsn() -> str:
    dsn = postgres_dsn()
    if not dsn:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    return dsn


async def _scoped_workspace(pg_pool: Any, label: str) -> tuple[PgProjectScopeStore, str, str]:
    """A fresh Workspace/Project pair, the house isolation pattern."""
    projects = PgProjectScopeStore(pg_pool)
    workspace = f"m8a7-{label}-{uuid4().hex}"
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Race"
    )
    return projects, workspace, project.project_id


def _race_graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="m8a7",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


class _Race:
    """Independent actor sessions, each a thread + event loop + private pool.

    ``stage`` runs one actor to completion on its own loop. A shared
    ``threading.Barrier`` (or an ``Event``) makes a chosen interleaving
    deterministic: every staged actor reaches the gate before any proceeds.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._results: list[Any] = [None] * ACTORS
        self._errors: list[BaseException | None] = [None] * ACTORS
        self._staged: list[int] = []
        self._threads: list[threading.Thread] = []

    def stage(self, index: int, coro_factory: Callable[[Any], Awaitable[Any]]) -> None:
        """Run ``coro_factory(pool)`` on actor ``index``'s private loop."""

        async def _actor_main() -> None:
            pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=2, init=_register_json_codecs
            )
            try:
                self._results[index] = await coro_factory(pool)
            except BaseException as exc:  # re-raised at join, named by actor
                self._errors[index] = exc
            finally:
                await pool.close()

        thread = threading.Thread(
            target=lambda: asyncio.run(_actor_main()), name=f"m8a7-actor-{index}", daemon=True
        )
        self._threads.append(thread)
        self._staged.append(index)
        thread.start()

    def join(self, timeout: float = 120.0) -> list[Any]:
        for thread in self._threads:
            thread.join(timeout)
            if thread.is_alive():
                pytest.fail(f"{thread.name} never finished; harness deadlocked")
        for index in self._staged:
            exc = self._errors[index]
            if exc is not None:
                raise AssertionError(f"actor {index} raised") from exc
        return [self._results[index] for index in self._staged]


async def _lock_wait_graph(witness: Any) -> dict[int, tuple[int, ...]]:
    """pid -> its direct blockers, for every session in this database.

    ``pg_blocking_pids`` reports *direct* blockers only: on a row-lock queue
    the second waiter's blocker is the first waiter, not the lock holder.
    The witness therefore reads the whole wait graph and checks that every
    actor is lock-waiting inside the race (blocker chains rooted at the
    held Run lock), not that each is blocked by the holder directly.
    """
    rows = await witness.fetch(
        """SELECT pid, pg_blocking_pids(pid) AS blocked_by
             FROM pg_stat_activity
            WHERE pid <> pg_backend_pid() AND datname = current_database()"""
    )
    return {row["pid"]: tuple(row["blocked_by"] or []) for row in rows}


@pytest.mark.asyncio
async def test_claim_race_from_independent_sessions_admits_one_physical_winner(
    pg_pool: Any, pg_dsn: str
) -> None:
    """Duplicate consumer claims across sessions -> exactly one physical claim.

    The contention witness is the point: while this test holds the Run row
    lock on an independent connection, all four actor backends must show up
    in ``pg_blocking_pids`` -- proof that each actor really runs its own
    session and the winner was chosen by the row lock, not by accident of a
    shared event loop. A harness that silently serialized the claims fails
    here before the outcome assertions could pass vacuously.
    """
    projects, workspace, project_id = await _scoped_workspace(pg_pool, "claim")
    main_store = PgRunStore(pg_pool, project_store=projects)
    run = await main_store.create_run(
        _race_graph(workspace, project_id),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        initial_status=RunStatus.QUEUED,
    )

    go = threading.Event()

    def claimant(name: str) -> Callable[[Any], Awaitable[Any]]:
        async def _claim(pool: Any) -> tuple[str, Any]:
            store = ClaimingPgRunStore(pool, project_store=PgProjectScopeStore(pool))
            assert go.wait(30), "claimant never released to start"
            try:
                claim = await store.claim_consumer_run(
                    run.run_id,
                    node_id="node-1",
                    runtime_id=f"rt-{name}",
                    executor_id=f"ex-{name}",
                    lease_ttl=CLAIM_LEASE,
                )
            except ConsumerClaimLost:
                return ("lost", None)
            return ("won", claim)

        return _claim

    race = _Race(pg_dsn)
    holder = await pg_pool.acquire()
    try:
        holder_pid = await holder.fetchval("SELECT pg_backend_pid()")
        async with holder.transaction():
            await holder.execute(
                "SELECT payload FROM canonical_runs WHERE run_id = $1 FOR UPDATE", run.run_id
            )
            for index in range(ACTORS):
                race.stage(index, claimant(f"actor-{index}"))
            go.set()
            deadline = time.monotonic() + CONTENTION_TIMEOUT_S
            waiting: dict[int, tuple[int, ...]] = {}
            while time.monotonic() < deadline:
                wait_graph = await _lock_wait_graph(pg_pool)
                waiting = {pid: b for pid, b in wait_graph.items() if b}
                # Every actor must be lock-waiting, the wait graph must sit
                # entirely inside the race (blocker chains rooted at the held
                # Run lock), and the holder must be the chain root.
                blockers = {b for chain in waiting.values() for b in chain}
                if (
                    len(waiting) >= ACTORS
                    and blockers <= {holder_pid, *waiting}
                    and holder_pid in blockers
                ):
                    break
                await asyncio.sleep(0.02)
            assert len(waiting) >= ACTORS, (
                "contention witness failed: not every actor backend was "
                f"lock-waiting on the held Run row lock (saw {len(waiting)} of "
                f"{ACTORS}, wait graph {waiting!r}); the race never raced, so "
                "its outcome would be vacuous"
            )
        # Exiting the transaction commits and releases the lock.
        race.join()
    finally:
        await holder.close()
        go.set()

    outcomes = race.join()
    winners = [claim for status, claim in outcomes if status == "won"]
    losers = [status for status, _ in outcomes if status == "lost"]
    assert len(winners) == 1, f"exactly one physical claim expected, got {len(winners)}"
    assert len(losers) == ACTORS - 1
    claim = winners[0]

    # One canonical claim in the database: one RUNNING Run, one NodeRun, one
    # RUNNING Attempt -- the "no third state, no second recovery mechanism"
    # contract from the claim module's own docstring.
    stored = await main_store.get_run(run.run_id)
    assert stored is not None and stored.status is RunStatus.RUNNING
    node_runs = await main_store.list_node_runs(run.run_id)
    assert len(node_runs) == 1
    attempts = await main_store.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.RUNNING
    assert node_runs[0].node_run_id == claim.node_run.node_run_id
    assert attempts[0].attempt_id == claim.attempt.attempt_id
    assert claim.attempt.execution_lease is not None


@pytest.mark.asyncio
async def test_effect_claim_read_none_insert_window_yields_one_row(
    pg_pool: Any, pg_dsn: str
) -> None:
    """The deliberate read-none/read-none/insert window elects exactly one run.

    Every actor reads "no run for this effect key" inside its own
    transaction, waits at the barrier until *all* have read none, and only
    then inserts -- the widest window the issue names, produced
    deterministically. The partial unique index ``ix_canonical_runs_effect``
    (migration 041) is the only thing that can resolve it; these are the
    statement shapes ``PgRunStore.claim_run_by_effect`` issues, against the
    same index, on bare scratch payloads.
    """
    _, workspace, project_id = await _scoped_workspace(pg_pool, "effect-window")
    effect_key = f"m8a7-window-{uuid4().hex}"
    payload = f'{{"provenance": {{"effect_key": "{effect_key}"}}}}'
    window = threading.Barrier(ACTORS)

    async def contender(pool: Any) -> bool:
        async with pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchval(
                """SELECT payload FROM canonical_runs
                   WHERE payload -> 'provenance' ->> 'effect_key' = $1
                   LIMIT 1""",
                effect_key,
            )
            assert existing is None, "the read-none half of the window was violated"
            window.wait(30)
            inserted = await conn.fetchrow(
                """INSERT INTO canonical_runs
                   (run_id, workspace_id, project_id, parent_run_id,
                    parent_node_run_id, status, payload, retention_expires_at)
                   VALUES ($1, $2, $3, NULL, NULL, 'created', $4::text::jsonb, NULL)
                   ON CONFLICT DO NOTHING
                   RETURNING run_id""",
                str(uuid4()),
                workspace,
                project_id,
                payload,
            )
            return inserted is not None

    race = _Race(pg_dsn)
    for index in range(ACTORS):
        race.stage(index, contender)
    race.join()

    created = [value for value in race.join() if value]
    assert len(created) == 1, f"the unique index must elect exactly one winner, got {len(created)}"
    rows = await pg_pool.fetch(
        """SELECT run_id FROM canonical_runs
           WHERE payload -> 'provenance' ->> 'effect_key' = $1""",
        effect_key,
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_store_effect_claim_race_yields_one_created_and_shared_identity(
    pg_pool: Any, pg_dsn: str
) -> None:
    """``claim_run_by_effect`` from independent stores: one creator, one run.

    The store-level counterpart to the window leg: four actors build real
    ``PgRunStore`` objects on private pools and race the real method, which
    must return ``created=True`` exactly once and the same canonical run to
    everyone.
    """
    _projects, workspace, project_id = await _scoped_workspace(pg_pool, "effect-store")
    effect_key = f"m8a7-store-{uuid4().hex}"
    go = threading.Event()

    def contender() -> Callable[[Any], Awaitable[Any]]:
        async def _claim(pool: Any) -> tuple[bool, str]:
            store = PgRunStore(pool, project_store=PgProjectScopeStore(pool))
            assert go.wait(30), "contender never released to start"
            effect = await store.claim_run_by_effect(
                _race_graph(workspace, project_id),
                effect_key=effect_key,
                actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            )
            return (effect.claimed, effect.run.run_id)

        return _claim

    race = _Race(pg_dsn)
    for index in range(ACTORS):
        race.stage(index, contender())
    go.set()
    race.join()

    outcomes = race.join()
    creators = [run_id for claimed, run_id in outcomes if claimed]
    assert len(creators) == 1
    run_ids = {run_id for _created, run_id in outcomes}
    assert len(run_ids) == 1, "every claimant must see the same canonical run"
    rows = await pg_pool.fetch(
        """SELECT run_id FROM canonical_runs
           WHERE payload -> 'provenance' ->> 'effect_key' = $1""",
        effect_key,
    )
    assert [row["run_id"] for row in rows] == list(run_ids)


@pytest.mark.asyncio
async def test_stale_writers_cannot_rewrite_a_terminalized_run(pg_pool: Any, pg_dsn: str) -> None:
    """Terminal state is monotone against stale writers (#1335's invariant).

    After the Run terminalizes FAILED: a stale success (Attempt COMPLETED)
    is refused inside the write transaction, a stale Run transition is
    refused by the lifecycle table, and the documented asymmetry holds -- a
    FAILED Attempt record stays legal under a terminal Run, because it
    records a true physical outcome rather than claiming unearned success.
    """
    projects, workspace, project_id = await _scoped_workspace(pg_pool, "stale")
    store = PgRunStore(pg_pool, project_store=projects)
    run = await store.create_run(
        _race_graph(workspace, project_id),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        initial_status=RunStatus.QUEUED,
    )
    claim = await ClaimingPgRunStore(pg_pool, project_store=projects).claim_consumer_run(
        run.run_id,
        node_id="node-1",
        runtime_id="rt-stale",
        executor_id="ex-stale",
        lease_ttl=CLAIM_LEASE,
    )
    lease = claim.attempt.execution_lease
    assert lease is not None

    await store.transition_run(run.run_id, RunStatus.FAILED, error="settled elsewhere")

    # The stale success: refused, and the Attempt row never moves.
    with pytest.raises(InvalidLifecycleTransition, match="terminal Run"):
        await store.transition_attempt(
            claim.attempt.attempt_id,
            AttemptStatus.COMPLETED,
            fencing_token=lease.fencing_token,
        )
    settled = await store.get_attempt(claim.attempt.attempt_id)
    assert settled is not None and settled.status is AttemptStatus.RUNNING

    # The asymmetry: recording the true failure underneath the terminal Run
    # is exactly what the crash-reclamation and cancel paths must be able to
    # do (lifecycle.refuse_completion_under_terminal_run's contract).
    failed = await store.transition_attempt(
        claim.attempt.attempt_id,
        AttemptStatus.FAILED,
        error="real outcome",
        fencing_token=lease.fencing_token,
    )
    assert failed.status is AttemptStatus.FAILED

    with pytest.raises(InvalidLifecycleTransition):
        await store.transition_run(run.run_id, RunStatus.CANCELLED)


@pytest.mark.asyncio
async def test_dueling_terminalizations_from_independent_actors_elect_one_winner(
    pg_pool: Any, pg_dsn: str
) -> None:
    """Two actors race different terminal statuses; exactly one lands.

    Both start from the same stale read of the RUNNING Run. The row lock
    decides: the loser re-reads after the winner commits and the lifecycle
    table refuses the second terminal write, so the final state is always a
    legal single terminal status -- never a splice of the two.
    """
    projects, workspace, project_id = await _scoped_workspace(pg_pool, "duel")
    main_store = PgRunStore(pg_pool, project_store=projects)
    run = await main_store.create_run(
        _race_graph(workspace, project_id),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        initial_status=RunStatus.QUEUED,
    )
    await main_store.transition_run(run.run_id, RunStatus.RUNNING)
    go = threading.Event()

    def terminalizer(target: RunStatus) -> Callable[[Any], Awaitable[Any]]:
        async def _settle(pool: Any) -> str:
            store = PgRunStore(pool, project_store=PgProjectScopeStore(pool))
            assert go.wait(30), "terminalizer never released to start"
            try:
                await store.transition_run(run.run_id, target, error=target.value)
            except InvalidLifecycleTransition as exc:
                return f"refused:{exc}"
            return f"landed:{target.value}"

        return _settle

    race = _Race(pg_dsn)
    race.stage(0, terminalizer(RunStatus.COMPLETED))
    race.stage(1, terminalizer(RunStatus.FAILED))
    go.set()
    race.join()

    outcomes = race.join()
    landed = [outcome for outcome in outcomes if outcome.startswith("landed:")]
    assert len(landed) == 1, f"exactly one terminalization may land, got {landed}"
    settled = await main_store.get_run(run.run_id)
    assert settled is not None
    assert settled.status.value == landed[0].split(":", 1)[1]
    assert settled.status in (RunStatus.COMPLETED, RunStatus.FAILED)


@pytest.mark.asyncio
async def test_invocation_claims_from_independent_actors_dispatch_exactly_once(
    pg_pool: Any, pg_dsn: str
) -> None:
    """A (trigger, event) is dispatched once across sessions; never twice.

    The single-statement claim upsert is the whole guarantee: one winner, the
    rest ``None``. After a terminal status lands, no session can re-claim it
    even with a lapsed lease.
    """
    await PgEventLog(pg_pool).ensure_schema()
    triggers = PgTriggerStore(pg_pool)
    await triggers.ensure_schema()
    trigger = TriggerDefinition(
        trigger_id=f"m8a7-{uuid4().hex[:8]}",
        name="race trigger",
        event_pattern="race.*",
        handler_url="http://127.0.0.1:9/handler",
    )
    await triggers.add(trigger)
    event = await PgEventLog(pg_pool).append("race.fired", entity_id="e-1")
    go = threading.Event()

    def claimer() -> Callable[[Any], Awaitable[Any]]:
        async def _claim(pool: Any) -> HandlerInvocation | None:
            store = PgInvocationStore(pool)
            assert go.wait(30), "claimer never released to start"
            return await store.claim(trigger.trigger_id, event.id, lease_seconds=0.05)

        return _claim

    race = _Race(pg_dsn)
    for index in range(ACTORS):
        race.stage(index, claimer())
    go.set()
    race.join()

    won = [invocation for invocation in race.join() if invocation is not None]
    assert len(won) == 1, f"exactly one dispatch per (trigger, event), got {len(won)}"
    winner = won[0]
    assert winner.status is InvocationStatus.PENDING

    # Terminal is terminal: even with the lease long lapsed, no session may
    # re-dispatch a SUCCESS invocation.
    store = PgInvocationStore(pg_pool)
    terminal = HandlerInvocation(
        trigger_id=winner.trigger_id,
        event_id=winner.event_id,
        status=InvocationStatus.SUCCESS,
        attempts=winner.attempts,
        last_error="",
        created_at=winner.created_at,
        lease_expires_at=time.time() - 3600,
    )
    await store.save(terminal)
    for _ in range(ACTORS):
        assert await store.claim(trigger.trigger_id, event.id, lease_seconds=0.05) is None

    rows = await store.list_for_event(event.id)
    assert len(rows) == 1
    assert rows[0].status is InvocationStatus.SUCCESS
    assert rows[0].attempts == 1, "terminal re-claim attempts must not increment"


@pytest.mark.asyncio
async def test_concurrent_event_appends_keep_a_unique_total_order(
    pg_pool: Any, pg_dsn: str
) -> None:
    """Ids from concurrent session appends are unique and totally ordered.

    The interleaving witness is structural: if the four actors' id ranges
    were disjoint contiguous blocks, the appends were serialized per session
    and the harness proved nothing. Concurrent sessions allocate from one
    sequence, so the actors' ranges must overlap.
    """
    log = PgEventLog(pg_pool)
    await log.ensure_schema()
    start = threading.Barrier(ACTORS)

    def appender(name: str) -> Callable[[Any], Awaitable[Any]]:
        async def _append(pool: Any) -> list[int]:
            actor_log = PgEventLog(pool)
            ids: list[int] = []
            start.wait(30)
            for index in range(EVENTS_PER_ACTOR):
                event = await actor_log.append(f"race.{name}", entity_id=f"{name}-{index}")
                ids.append(event.id)
            return ids

        return _append

    race = _Race(pg_dsn)
    for index in range(ACTORS):
        race.stage(index, appender(f"actor-{index}"))
    race.join()

    per_actor: list[list[int]] = race.join()
    all_ids = [event_id for ids in per_actor for event_id in ids]
    assert len(all_ids) == ACTORS * EVENTS_PER_ACTOR
    assert len(set(all_ids)) == len(all_ids), "sequence ids must never collide"

    lows = [min(ids) for ids in per_actor]
    highs = [max(ids) for ids in per_actor]
    overall_lo, overall_hi = min(lows), max(highs)
    overlapped = any(
        overall_lo < high and low < overall_hi for low, high in zip(lows, highs, strict=True)
    )
    assert overlapped, (
        "per-actor id ranges are disjoint contiguous blocks: the appends "
        "serialized per session and the race never raced"
    )

    # One total order: pagination by after_id walks every event exactly once,
    # in id order.
    walked: list[int] = []
    after = 0
    while True:
        page = await log.query(after_id=after, limit=7)
        if not page:
            break
        walked.extend(event.id for event in page)
        assert [event.id for event in page] == sorted(event.id for event in page)
        after = page[-1].id
    assert walked == sorted(set(all_ids))


@pytest.mark.asyncio
async def test_cursor_lease_reclaim_fences_the_stale_holder(pg_pool: Any, pg_dsn: str) -> None:
    """A reclaimed cursor lease fences the old holder's writes.

    Cross-session: after another session re-claims the expired lease, the
    stale holder tries to advance with its old fencing token and must be
    refused; the new holder advances; and the durable position never moves
    backwards.
    """
    store = PgConsumerCursorStore(pg_pool)
    await store.ensure_schema()
    consumer = f"m8a7-cursor-{uuid4().hex}"
    go = threading.Event()

    def reclaimer() -> Callable[[Any], Awaitable[Any]]:
        async def _claim(pool: Any) -> Any:
            actor_store = PgConsumerCursorStore(pool)
            assert go.wait(30), "reclaimer never released to start"
            return await actor_store.claim(consumer, holder="holder-B", lease_seconds=30.0)

        return _claim

    first = await store.claim(consumer, holder="holder-A", lease_seconds=0.05)
    assert first is not None
    await asyncio.sleep(0.06)  # let holder-A's lease lapse deliberately

    race = _Race(pg_dsn)
    race.stage(0, reclaimer())
    go.set()
    race.join()
    second = race.join()[0]
    assert second is not None, "an expired lease must be reclaimable by a new holder"
    assert second.fencing_token != first.fencing_token

    # The stale holder's write is refused outright.
    assert not await store.advance(consumer, fencing_token=first.fencing_token, position=100)
    # The new holder advances; a stale low position cannot move it backwards.
    assert await store.advance(consumer, fencing_token=second.fencing_token, position=5)
    renewed = await store.claim(consumer, holder="holder-B", lease_seconds=30.0)
    assert renewed is not None
    assert renewed.position >= 5


@pytest.mark.asyncio
async def test_no_new_node_run_under_a_terminal_run_from_an_independent_session(
    pg_pool: Any, pg_dsn: str
) -> None:
    """Spine integrity: a stale session cannot extend a finished Run.

    An actor that read the Run before it terminalized still must not be able
    to hang a new NodeRun under it: the create re-reads the parent under the
    Run lock in the same transaction and refuses.
    """
    projects, workspace, project_id = await _scoped_workspace(pg_pool, "spine")
    main_store = PgRunStore(pg_pool, project_store=projects)
    run = await main_store.create_run(
        _race_graph(workspace, project_id),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        initial_status=RunStatus.QUEUED,
    )
    await main_store.transition_run(run.run_id, RunStatus.RUNNING)
    await main_store.transition_run(run.run_id, RunStatus.FAILED)

    stale_pool = await asyncpg.create_pool(
        pg_dsn, min_size=1, max_size=1, init=_register_json_codecs
    )
    try:
        stale_store = PgRunStore(stale_pool, project_store=PgProjectScopeStore(stale_pool))
        with pytest.raises(RunIntegrityError, match="terminal"):
            await stale_store.create_node_run(run.run_id, node_id="node-1")
    finally:
        await stale_pool.close()
