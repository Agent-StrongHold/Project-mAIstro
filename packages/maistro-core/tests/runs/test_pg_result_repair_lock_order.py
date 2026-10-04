"""`PgRunStore.repair_attempt_result` locks parent-first: Run → NodeRun → Attempt (#1888).

`record_eval_score`, the archive sweep, and every cascade in this store lock
the Run before its NodeRun before its Attempt. The result repair was the one
writer that locked the Attempt first — a real inversion, not a style
preference: between its locks it held the Attempt while waiting for the
NodeRun an eval writer already held, so the eval writer's next lock (the
Attempt) waited on the repair. One more step and PostgreSQL resolves the cycle
by aborting one of the two operations.

Two legs, like the other PG suites here.

The stand-in leg routes the repair's statements by shape against real spine
payloads, so the no-services leg proves the order the method actually issues —
lineage read, Run FOR UPDATE, NodeRun FOR UPDATE, Attempt FOR UPDATE, then the
writes — that the Run lock carries no payload hydration, and that every
refusal lands before any write. What a stand-in cannot prove is that the locks
actually contend, so the PG-gated leg runs the pair for real: a
`record_eval_score` holds the Run and NodeRun row locks while paused before
its Attempt lock, and the repair must be observed — through `pg_blocking_pids`
on an independent connection — blocked behind it *without* having taken the
Attempt lock, then complete once the eval writer commits. Under the old
Attempt-first order the repair takes the Attempt lock first and the pair
deadlocks; this test fails against that order rather than merely preferring
the new one.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.evidence_json import payload_of
from maistro.runs.model import (
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    EvalMethod,
    NodeRun,
    Run,
    RunEvalScore,
    RunStatus,
)
from maistro.runs.store import (
    AttemptNotFound,
    InMemoryRunStore,
    RunIntegrityError,
    validate_accepted_outcome_against_attempt,
)
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

GOAL_ID = "goal-homestead"
RUBRIC_ID = "rubric-homestead"

#: What a node that returned a typed model persisted as before #566 — the
#: emptied output a repair puts right.
EMPTIED = {"status": "completed", "success": True, "output": {}}
RECOVERED = {"title": "a typed model's own fields", "pages": 12}


class _Row(dict):
    """asyncpg rows are mapping-like; a plain dict subclass is enough."""


class _RepairPool:
    """The statements `repair_attempt_result` makes, answered in memory.

    Routing is by statement shape, not by call position: a store edit that
    stops issuing the parent-first sequence fails here loudly instead of
    passing because the stub happened to be asked in the right order.
    """

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}  # run_id -> payload
        self.node_runs: dict[str, dict[str, Any]] = {}  # node_run_id -> payload
        self.attempts: dict[str, dict[str, Any]] = {}  # attempt_id -> payload
        # The promoted relational columns the real tables carry beside the
        # payload (migration 012): kept separate so a test can corrupt a
        # payload field without also moving what the relational JOIN sees.
        self.attempt_nodes: dict[str, str] = {}  # attempt_id -> node_run_id
        self.node_run_runs: dict[str, str] = {}  # node_run_id -> run_id
        #: SQL text of every statement, in order — the lock-order assertions
        #: read this rather than trusting the method's comments.
        self.statements: list[str] = []
        #: (table, identity) of every UPDATE, in write order.
        self.updates: list[tuple[str, str]] = []

    def acquire(self) -> _RepairPool:
        return self

    async def __aenter__(self) -> _RepairPool:
        return self

    async def __aexit__(self, *_exc_info: object) -> bool:
        return False

    def transaction(self) -> _RepairPool:
        return self

    async def fetchrow(self, query: str, *args: object) -> _Row | None:
        sql = " ".join(query.split())
        self.statements.append(sql)
        if "JOIN canonical_node_runs" in sql:
            attempt_id = str(args[0])
            node_run_id = self.attempt_nodes.get(attempt_id)
            if node_run_id is None or node_run_id not in self.node_run_runs:
                return None
            return _Row(node_run_id=node_run_id, run_id=self.node_run_runs[node_run_id])
        if "FOR UPDATE" not in sql:
            raise AssertionError(f"unexpected fetchrow query: {query!r}")
        if "canonical_runs" in sql:
            # The identity-only Run lock: what the method must NOT send is a
            # payload select behind this lock.
            return _Row(run_id=str(args[0])) if str(args[0]) in self.runs else None
        if "canonical_node_runs" in sql:
            payload = self.node_runs.get(str(args[0]))
            return _Row(node_run_id=str(args[0]), payload=payload, archive_key=None)
        if "canonical_attempts" in sql:
            payload = self.attempts.get(str(args[0]))
            return _Row(attempt_id=str(args[0]), payload=payload, archive_key=None)
        raise AssertionError(f"unexpected FOR UPDATE query: {query!r}")

    async def execute(self, query: str, *args: object) -> str:
        sql = " ".join(query.split())
        self.statements.append(sql)
        for table in ("canonical_attempts", "canonical_node_runs"):
            if f"UPDATE {table}" in sql:
                identity = str(args[2])
                payload = json.loads(str(args[1]))
                if table == "canonical_attempts":
                    self.attempts[identity] = payload
                else:
                    self.node_runs[identity] = payload
                self.updates.append((table, identity))
                return "UPDATE 1"
        raise AssertionError(f"unexpected execute query: {query!r}")

    async def fetchval(self, query: str, *args: object) -> object:
        raise AssertionError(f"unexpected fetchval query: {query!r}")


async def _repair_pool() -> tuple[_RepairPool, str]:
    """A stand-in pool loaded with one accepted-emptied spine; the attempt id.

    The spine is built by running a real store the way production runs it —
    create, transition, accept — so the payloads are real serialisations, the
    shape `test_attempt_result_repair.py` argues for.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="w1",
        project_id=root.project_id,
        name="g",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result=EMPTIED
    )
    node_run = await store.transition_node_run(
        node_run.node_run_id,
        RunStatus.COMPLETED,
        result=RECOVERED,
        accepted_outcome=AcceptedNodeOutcome(
            node_run_id=node_run.node_run_id,
            attempt_result=AttemptResult.from_attempt(attempt),
            logical_status=RunStatus.COMPLETED,
            result=RECOVERED,
        ),
    )
    pool = _RepairPool()
    pool.runs[run.run_id] = payload_of(run)
    pool.node_runs[node_run.node_run_id] = payload_of(node_run)
    pool.attempts[attempt.attempt_id] = payload_of(attempt)
    pool.attempt_nodes[attempt.attempt_id] = attempt.node_run_id
    pool.node_run_runs[node_run.node_run_id] = node_run.run_id
    return pool, attempt.attempt_id


def _store(pool: _RepairPool) -> Any:
    from maistro.runs.pg_store import PgRunStore

    return PgRunStore(pool, project_store=InMemoryProjectScopeStore())  # type: ignore[arg-type]


def _first(pool: _RepairPool, sql: str) -> int:
    """Index of the first statement containing `sql`, or -1."""
    return next((i for i, s in enumerate(pool.statements) if sql in s), -1)


class TestTheStatementsLockParentFirst:
    """The order the method issues, read off the statements themselves."""

    async def test_run_then_node_run_then_attempt_then_the_writes(self) -> None:
        pool, attempt_id = await _repair_pool()
        store = _store(pool)

        repaired = await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        assert repaired.result["output"] == RECOVERED
        lineage = _first(pool, "JOIN canonical_node_runs")
        run_lock = _first(pool, "FROM canonical_runs WHERE")
        node_lock = _first(pool, "FROM canonical_node_runs WHERE")
        attempt_lock = _first(pool, "FROM canonical_attempts WHERE")
        # Every lock found, and in the store-wide parent-first order. The
        # lineage read is not part of the order — it is deliberately
        # unlocked — but it happens before any lock can wait on another
        # writer.
        assert -1 not in (lineage, run_lock, node_lock, attempt_lock)
        assert "FOR UPDATE" not in pool.statements[lineage]
        assert lineage < run_lock < node_lock < attempt_lock
        # Both payloads committed, in one transaction, Attempt first.
        node_run_id = next(iter(pool.node_runs))
        assert pool.updates == [
            ("canonical_attempts", attempt_id),
            ("canonical_node_runs", node_run_id),
        ]
        assert _first(pool, "UPDATE canonical_attempts") > attempt_lock
        assert _first(pool, "UPDATE canonical_node_runs") > attempt_lock

    async def test_the_run_lock_is_identity_only(self) -> None:
        """Ordering and existence, not hydration: the Run's payload — possibly
        archive-backed — is neither read nor validated by a repair."""
        pool, attempt_id = await _repair_pool()
        store = _store(pool)

        await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        run_lock = next(sql for sql in pool.statements if "FROM canonical_runs" in sql)
        assert "FOR UPDATE" in run_lock
        assert "payload" not in run_lock
        assert "archive_key" not in run_lock

    async def test_a_terminal_run_over_a_terminal_attempt_stays_repairable(self) -> None:
        """The repair gate is the Attempt's own status. A Run that finished
        first must not — through the new parent lock — become a second,
        unasked-for refusal."""
        pool, attempt_id = await _repair_pool()
        run_id = next(iter(pool.runs))
        pool.runs[run_id]["status"] = RunStatus.COMPLETED.value
        store = _store(pool)

        repaired = await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        assert repaired.result["output"] == RECOVERED


class TestTheRefusalsComeBeforeAnyWrite:
    async def test_a_missing_attempt_names_the_target_and_locks_nothing(self) -> None:
        pool, _attempt_id = await _repair_pool()
        store = _store(pool)

        with pytest.raises(AttemptNotFound):
            await store.repair_attempt_result("attempt-nowhere", result={"output": RECOVERED})

        # The lineage read answered; no row was ever locked, nothing written.
        assert len(pool.statements) == 1
        assert "FOR UPDATE" not in pool.statements[0]
        assert pool.updates == []

    async def test_a_deleted_lineage_reports_the_target_gone(self) -> None:
        """delete_run removes the whole lineage under the Run's lock. A repair
        that read the lineage just before that commit finds the Run row gone
        at lock time — the target went with it, so the error names the
        Attempt, not a Run the caller never asked about."""
        pool, attempt_id = await _repair_pool()
        pool.runs.clear()
        store = _store(pool)

        with pytest.raises(AttemptNotFound):
            await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        assert pool.updates == []
        assert any("FROM canonical_runs" in sql for sql in pool.statements)

    async def test_a_nonterminal_attempt_is_refused_before_any_write(self) -> None:
        pool, attempt_id = await _repair_pool()
        pool.attempts[attempt_id]["status"] = AttemptStatus.RUNNING.value
        pool.attempts[attempt_id]["finished_at"] = None
        store = _store(pool)

        with pytest.raises(RunIntegrityError, match="has not finished"):
            await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        assert pool.updates == []
        # Refused only after the lineage was locked and re-read: the verdict
        # is the live row's, not a pre-lock snapshot's.
        assert any(
            "FROM canonical_attempts" in sql and "FOR UPDATE" in sql for sql in pool.statements
        )


class TestTheLockedReReadVerifiesLineage:
    """The lineage was read unlocked; the locked re-read is what the write
    trusts. A payload that disagrees with the relational lineage it was
    resolved from is corruption a repair must refuse — not a different
    identity it may silently recover."""

    async def test_an_attempt_payload_pointing_elsewhere_is_refused(self) -> None:
        pool, attempt_id = await _repair_pool()
        pool.attempts[attempt_id]["node_run_id"] = "node-run-elsewhere"
        store = _store(pool)

        with pytest.raises(RunIntegrityError, match="lineage changed under the repair lock"):
            await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        assert pool.updates == []

    async def test_a_node_run_payload_pointing_elsewhere_is_refused(self) -> None:
        pool, attempt_id = await _repair_pool()
        node_run_id = next(iter(pool.node_runs))
        pool.node_runs[node_run_id]["run_id"] = "run-elsewhere"
        store = _store(pool)

        with pytest.raises(RunIntegrityError, match="lineage changed under the repair lock"):
            await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        assert pool.updates == []


class TestTheAcceptedCopy:
    async def test_an_unaccepted_attempt_repairs_without_a_node_run_write(self) -> None:
        pool, attempt_id = await _repair_pool()
        node_run_id = next(iter(pool.node_runs))
        pool.node_runs[node_run_id]["accepted_outcome"] = None
        store = _store(pool)

        repaired = await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        assert repaired.result["output"] == RECOVERED
        assert pool.updates == [("canonical_attempts", attempt_id)]

    async def test_the_accepted_outcome_moves_with_the_attempt(self) -> None:
        pool, attempt_id = await _repair_pool()
        store = _store(pool)

        repaired = await store.repair_attempt_result(attempt_id, result={"output": RECOVERED})

        node_run_id = next(iter(pool.node_runs))
        outcome = pool.node_runs[node_run_id]["accepted_outcome"]
        # One transaction carried both payloads: the embedded physical copy
        # matches the Attempt this same method just wrote.
        assert outcome is not None
        assert outcome["attempt_result"]["result"]["output"] == RECOVERED
        assert pool.attempts[attempt_id]["result"]["output"] == RECOVERED
        assert repaired.attempt_id == attempt_id


# ── the real-PG leg: the locks actually contend ───────────────────


class _SpyConn:
    """A real asyncpg connection that logs every statement it is asked to run.

    The optional gate runs *before* a statement is issued, so pausing on the
    Attempt FOR UPDATE means the two locks above it are genuinely held by this
    transaction when the test proceeds — held rows, not a started task.
    """

    def __init__(self, conn: Any, log: list[str], gate: Any) -> None:
        self._conn = conn
        self._log = log
        self._gate = gate
        self.backend_pid: int = conn.get_server_pid()

    def transaction(self) -> Any:
        return self._conn.transaction()

    async def execute(self, query: str, *args: object) -> Any:
        sql = " ".join(query.split())
        if self._gate is not None:
            await self._gate(sql)
        self._log.append(sql)
        return await self._conn.execute(query, *args)

    async def fetchrow(self, query: str, *args: object) -> Any:
        sql = " ".join(query.split())
        if self._gate is not None:
            await self._gate(sql)
        self._log.append(sql)
        return await self._conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: object) -> Any:
        sql = " ".join(query.split())
        if self._gate is not None:
            await self._gate(sql)
        self._log.append(sql)
        return await self._conn.fetchval(query, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class _SpyAcquire:
    def __init__(self, pool: Any, log: list[str], gate: Any) -> None:
        self._pool = pool
        self._log = log
        self._gate = gate
        self._conn: Any = None

    async def __aenter__(self) -> _SpyConn:
        self._conn = await self._pool.acquire()
        return _SpyConn(self._conn, self._log, self._gate)

    async def __aexit__(self, *_exc_info: object) -> bool:
        await self._pool.release(self._conn)
        return False


class _SpyPool:
    """Instrumented pool wrapper; one writer per role via max_size=1."""

    def __init__(self, pool: Any, log: list[str], gate: Any = None) -> None:
        self._pool = pool
        self._log = log
        self._gate = gate

    def acquire(self) -> _SpyAcquire:
        return _SpyAcquire(self._pool, self._log, self._gate)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pool, name)


async def _accepted_emptied_attempt(
    store: Any, workspace: str, project_id: str
) -> tuple[Run, NodeRun, Attempt]:
    graph = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Durable graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result=EMPTIED
    )
    accepted = await store.transition_node_run(
        node_run.node_run_id,
        RunStatus.COMPLETED,
        result=RECOVERED,
        accepted_outcome=AcceptedNodeOutcome(
            node_run_id=node_run.node_run_id,
            attempt_result=AttemptResult.from_attempt(attempt),
            logical_status=RunStatus.COMPLETED,
            result=RECOVERED,
        ),
    )
    return run, accepted, attempt


def _score(run_id: str, node_run_id: str, attempt_id: str) -> RunEvalScore:
    return RunEvalScore(
        eval_id="eval-contrast",
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        goal_id=GOAL_ID,
        goal_revision=4,
        rubric_id=RUBRIC_ID,
        rubric_revision=2,
        dimension_id="contrast",
        raw_score=0.2,
        passed=False,
        method=EvalMethod.DETERMINISTIC,
        evidence_pointers=[f"attempt:{attempt_id}/evidence/contrast"],
        detail={"threshold": 0.7},
    )


def _terminate(pools: list[Any]) -> None:
    """Best-effort close so a failed assertion does not leak pool tasks."""
    for raw in pools:
        with contextlib.suppress(Exception):
            raw.terminate()


async def test_repair_waits_parent_first_behind_an_eval_writer(pg_pool: Any) -> None:
    """The primary fail-before/pass-after oracle.

    An eval writer holds the Run and NodeRun locks, paused before its Attempt
    lock. A repair must be observed — through pg_blocking_pids on an
    independent connection — blocked behind that writer while holding no
    Attempt lock, then complete after the writer commits. The Attempt-first
    order this replaces takes the Attempt lock first and deadlocks here.
    """
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.persistence import _register_json_codecs
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore
    from maistro.testing.postgres import postgres_dsn

    dsn = postgres_dsn()
    projects = PgProjectScopeStore(pg_pool)
    workspace = "workspace-1-repair-lock-order"
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Durable"
    )
    store = PgRunStore(pg_pool, project_store=projects)
    run, node_run, attempt = await _accepted_emptied_attempt(store, workspace, project.project_id)

    # Separate pools pin separate backends for the competitor, the repair and
    # the observer; the assertions use their real pg_backend_pid values.
    pids: dict[str, int] = {}
    pools: list[Any] = []
    try:
        for role in ("repair", "eval", "observer"):
            raw = await asyncpg.create_pool(dsn, min_size=1, max_size=1, init=_register_json_codecs)
            pools.append(raw)
            async with raw.acquire() as probe:
                pids[role] = probe.get_server_pid()

        release_eval = asyncio.Event()
        eval_paused = asyncio.Event()

        async def pause_before_attempt_lock(sql: str) -> None:
            if "canonical_attempts" in sql and "FOR UPDATE" in sql:
                eval_paused.set()
                await release_eval.wait()

        eval_log: list[str] = []
        repair_log: list[str] = []
        eval_store = PgRunStore(
            _SpyPool(pools[1], eval_log, pause_before_attempt_lock), project_store=projects
        )
        repair_store = PgRunStore(_SpyPool(pools[0], repair_log), project_store=projects)

        eval_task = asyncio.create_task(
            eval_store.record_eval_score(
                _score(run.run_id, node_run.node_run_id, attempt.attempt_id)
            )
        )
        # The barrier means exactly this: the Run and NodeRun FOR UPDATE have
        # actually returned on the eval connection before the repair starts.
        await asyncio.wait_for(eval_paused.wait(), 10)

        repair_task = asyncio.create_task(
            repair_store.repair_attempt_result(attempt.attempt_id, result={"output": RECOVERED})
        )

        # Observed through the independent observer connection: the repair is
        # blocked by the eval writer's backend — not inferred from elapsed
        # time or from the task having started.
        async with pools[2].acquire() as observer:
            deadline = time.monotonic() + 10
            while True:
                blocked = await observer.fetchval(
                    "SELECT $1::int = ANY(pg_blocking_pids($2::int))",
                    pids["eval"],
                    pids["repair"],
                )
                if blocked:
                    break
                if time.monotonic() > deadline:
                    pytest.fail(
                        "repair was never observed blocked behind the eval writer; "
                        f"repair statements so far: {repair_log!r}"
                    )
                await asyncio.sleep(0.01)

        # The order proof, at the moment of the observed block: the repair has
        # taken the Run lock and holds no Attempt lock. The old Attempt-first
        # order fails here — its log already contains the Attempt FOR UPDATE.
        assert any("FROM canonical_runs" in s and "FOR UPDATE" in s for s in repair_log)
        assert not any("canonical_attempts" in s and "FOR UPDATE" in s for s in repair_log)
        # And the eval writer really is paused exactly between its own locks.
        assert any("canonical_node_runs" in s and "FOR UPDATE" in s for s in eval_log)

        release_eval.set()
        scored = await asyncio.wait_for(eval_task, 30)
        repaired = await asyncio.wait_for(repair_task, 30)

        assert scored.eval_id == "eval-contrast"
        assert repaired.result["output"] == RECOVERED
        reloaded = await store.get_attempt(attempt.attempt_id)
        outcome_row = await store.get_node_run(node_run.node_run_id)
        assert reloaded is not None and outcome_row is not None
        assert outcome_row.accepted_outcome is not None
        assert outcome_row.accepted_outcome.attempt_result.result["output"] == RECOVERED
        assert outcome_row.accepted_outcome.result == RECOVERED  # logical projection untouched
        validate_accepted_outcome_against_attempt(outcome_row.accepted_outcome, reloaded)
        assert [s.eval_id for s in await store.list_eval_scores(run.run_id)] == ["eval-contrast"]
    finally:
        _terminate(pools)
