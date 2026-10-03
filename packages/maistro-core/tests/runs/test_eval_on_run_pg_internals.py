"""`PgRunStore`'s eval-score statements, executed where they are reachable (#792).

The `spine` conformance fixture drives the eval-on-Run contract against a real
PostgreSQL when one is up. The no-services coverage producer has no server, and
the diff-coverage gate is right to refuse SQL statements nothing executed: a
typo in a column list would otherwise ship green. These tests run the eval
statements against a stand-in pool that routes by statement shape — the same
seam `test_pg_store_internals.py` uses — so the no-services leg proves the
statement text, the spine-guard refusals, and the deletion order retention and
`delete_run` owe the eval rows.

What a stand-in cannot prove is left to the PG-gated leg: constraint
enforcement, JSONB behaviour, concurrent transactions. What it *can* prove is
exactly what the gate needs: every statement this store makes about
`canonical_run_eval_scores` is made in the right order, with the right columns,
and behind the right refusals.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.evidence_json import payload_of
from maistro.runs.model import (
    Attempt,
    AttemptStatus,
    EvalMethod,
    NodeRun,
    Run,
    RunEvalScore,
    RunStatus,
)
from maistro.runs.pg_store import PgRunStore
from maistro.runs.retention_scope import GlobalRetentionScope
from maistro.runs.store import (
    AttemptNotFound,
    InMemoryRunStore,
    NodeRunNotFound,
    PurgeOutcome,
    RunIntegrityError,
    RunNotFound,
)

GOAL_ID = "goal-homestead"
RUBRIC_ID = "rubric-homestead"


class _Row(dict):
    """asyncpg rows are mapping-like; a plain dict subclass is enough."""


class _EvalPool:
    """The statements the eval-score methods make, answered in memory.

    Routing is by statement shape, not by call order: a store edit that stops
    making a statement fails here loudly, which is the property the coverage
    gate wants from this leg.
    """

    def __init__(self) -> None:
        # Spine payloads as dicts: the store's own pool registers a JSON
        # codec, so asyncpg hands the model validators objects, not text —
        # the shape these statements are written against.
        self.runs: dict[str, dict[str, Any]] = {}  # run_id -> payload
        self.node_runs: dict[str, dict[str, Any]] = {}  # node_run_id -> payload
        self.attempts: dict[str, dict[str, Any]] = {}  # attempt_id -> payload
        self.eval_rows: dict[str, str] = {}  # eval_id -> payload JSON
        #: eval_id -> run_id, insert order preserved for the listing test.
        self.eval_inserts: list[tuple[str, str]] = []
        #: eval_ids the duplicate guard reports as already committed.
        self.duplicate_eval_ids: set[str] = set()
        #: run_ids the retention candidate SELECT locks.
        self.purge_candidates: list[str] = []
        #: SQL text of every statement (`execute` and `fetch`), in order —
        #: the cascade assertions read this rather than trusting the method's
        #: comments. RETURNING-cascade deletes arrive through `fetch`.
        self.statements: list[str] = []
        #: Arguments of the most recent eval INSERT, for column assertions.
        self.last_eval_insert_args: tuple[Any, ...] | None = None

    def acquire(self) -> _EvalPool:
        return self

    async def __aenter__(self) -> _EvalPool:
        return self

    async def __aexit__(self, *_exc_info: object) -> bool:
        return False

    def transaction(self) -> _EvalPool:
        return self

    async def fetchval(self, query: str, *args: object) -> object:
        if "canonical_run_eval_scores" in query and "eval_id = $1" in query:
            return 1 if str(args[0]) in self.duplicate_eval_ids else None
        if "COUNT(*)" in query:
            return 0
        if "to_regclass" in query:
            return None
        raise AssertionError(f"unexpected fetchval query: {query!r}")

    async def fetchrow(self, query: str, *args: object) -> _Row | None:
        if "SELECT status FROM canonical_runs" in query:
            payload = self.runs.get(str(args[0]))
            if payload is None:
                return None
            return _Row(status=payload["status"])
        if "canonical_run_eval_scores" in query:
            payload = self.eval_rows.get(str(args[0]))
            return _Row(payload=payload) if payload is not None else None
        if "FOR UPDATE" in query:
            rows = (
                self.node_runs
                if "canonical_node_runs" in query
                else self.attempts
                if "canonical_attempts" in query
                else self.runs
            )
            payload = rows.get(str(args[0]))
            return _Row(payload=payload) if payload is not None else None
        if "archive_key" in query:
            payload = self.runs.get(str(args[0]))
            if payload is None:
                return None
            return _Row(run_id=str(args[0]), payload=payload, archive_key=None)
        raise AssertionError(f"unexpected fetchrow query: {query!r}")

    async def fetch(self, query: str, *args: object) -> list[_Row]:
        self.statements.append(" ".join(query.split()))
        if "retention_expires_at" in query:
            return [_Row(run_id=run_id) for run_id in self.purge_candidates]
        if "canonical_run_eval_scores" in query:
            run_id = str(args[0])
            return [
                _Row(payload=self.eval_rows[eval_id])
                for eval_id, scored_run in self.eval_inserts
                if scored_run == run_id
            ]
        if "DELETE FROM canonical_attempts" in query:
            return [_Row(attempt_id=f"a-{run_id}") for run_id in _ids(args)]
        if "DELETE FROM canonical_node_runs" in query:
            return [_Row(node_run_id=f"n-{run_id}") for run_id in _ids(args)]
        if "DELETE FROM canonical_runs" in query:
            return [_Row(run_id=run_id) for run_id in _ids(args)]
        raise AssertionError(f"unexpected fetch query: {query!r}")

    async def execute(self, query: str, *args: object) -> None:
        self.statements.append(" ".join(query.split()))
        if "INSERT INTO canonical_run_eval_scores" in query:
            self.last_eval_insert_args = args
            eval_id, run_id = str(args[0]), str(args[1])
            self.eval_rows[eval_id] = str(args[5])
            self.eval_inserts.append((eval_id, run_id))


def _ids(args: tuple[object, ...]) -> list[str]:
    """The text[] parameter of a `= ANY($1::text[])` cascade statement."""
    return [str(value) for value in args[0]]  # type: ignore[arg-type]


async def _spine() -> tuple[InMemoryRunStore, Run, NodeRun, Attempt]:
    """A real Run → NodeRun → completed Attempt, built on the in-memory store.

    The payloads the stand-in pool serves are the real serialisations of these
    rows, so the store's spine validation runs against actual models — a stub
    here would only prove the stub agrees with itself.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="w1",
        project_id=root.project_id,
        name="g",
        nodes=[Node(node_id="n1", node_type="agent", name="a")],
    )
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="n1")
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"artifact": "brief-v1"}
    )
    return store, run, node_run, attempt


def _score(
    run_id: str, node_run_id: str, attempt_id: str, *, dimension: str = "contrast"
) -> RunEvalScore:
    return RunEvalScore(
        eval_id=f"eval-{dimension}",
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        goal_id=GOAL_ID,
        goal_revision=4,
        rubric_id=RUBRIC_ID,
        rubric_revision=2,
        dimension_id=dimension,
        raw_score=0.2,
        passed=False,
        method=EvalMethod.DETERMINISTIC,
        evidence_pointers=[f"attempt:{attempt_id}/evidence/{dimension}"],
        detail={"threshold": 0.7},
    )


async def _pool_with_spine() -> tuple[_EvalPool, RunEvalScore]:
    _store, run, node_run, attempt = await _spine()
    pool = _EvalPool()
    pool.runs[run.run_id] = payload_of(run)
    pool.node_runs[node_run.node_run_id] = payload_of(node_run)
    pool.attempts[attempt.attempt_id] = payload_of(attempt)
    return pool, _score(run.run_id, node_run.node_run_id, attempt.attempt_id)


def _store(pool: _EvalPool) -> PgRunStore:
    return PgRunStore(pool, project_store=InMemoryProjectScopeStore())  # type: ignore[arg-type]


async def test_the_insert_persists_the_whole_record_under_its_eval_id() -> None:
    """The durable payload is the score itself, keyed by every spine id."""
    pool, failing = await _pool_with_spine()
    store = _store(pool)

    recorded = await store.record_eval_score(failing)

    assert recorded == failing
    assert pool.last_eval_insert_args is not None
    (
        eval_id,
        run_id,
        node_run_id,
        attempt_id,
        scored_at,
        payload,
    ) = pool.last_eval_insert_args
    assert eval_id == failing.eval_id
    assert run_id == failing.run_id
    assert node_run_id == failing.node_run_id
    assert attempt_id == failing.attempt_id
    assert scored_at == failing.scored_at.isoformat()
    durable = json.loads(str(payload))
    assert durable["dimension_id"] == "contrast"
    assert durable["passed"] is False
    assert durable["goal_id"] == GOAL_ID
    assert durable["rubric_id"] == RUBRIC_ID


async def test_a_committed_duplicate_eval_id_is_refused_before_any_insert() -> None:
    """Append-only means the second write of an eval_id never lands."""
    pool, _failing = await _pool_with_spine()
    pool.duplicate_eval_ids.add(_failing.eval_id)
    store = _store(pool)

    with pytest.raises(RunIntegrityError, match="already recorded"):
        await store.record_eval_score(_failing)

    assert not any("INSERT INTO" in sql for sql in pool.statements)


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("run", RunNotFound),
        ("node_run", NodeRunNotFound),
        ("attempt", AttemptNotFound),
    ],
)
async def test_scoring_requires_the_whole_spine(missing: str, expected: type[Exception]) -> None:
    """Each spine row is locked and read before anything is inserted."""
    pool, failing = await _pool_with_spine()
    {  # The named row simply is not there.
        "run": lambda: pool.runs.clear(),
        "node_run": lambda: pool.node_runs.clear(),
        "attempt": lambda: pool.attempts.clear(),
    }[missing]()
    store = _store(pool)

    with pytest.raises(expected):
        await store.record_eval_score(failing)

    assert not any("INSERT INTO" in sql for sql in pool.statements)


async def test_an_eval_record_cannot_dangle_off_the_spine() -> None:
    """An Attempt from another NodeRun is refused, insert and all."""
    store, run, node_run, _attempt = await _spine()
    other_node_run = await store.create_node_run(run.run_id, node_id="n1")
    other_attempt = await store.create_attempt(other_node_run.node_run_id)
    await store.transition_attempt(other_attempt.attempt_id, AttemptStatus.RUNNING)
    other_attempt = await store.transition_attempt(
        other_attempt.attempt_id, AttemptStatus.COMPLETED, result={"artifact": "brief-v1"}
    )

    pool = _EvalPool()
    pool.runs[run.run_id] = payload_of(run)
    pool.node_runs[node_run.node_run_id] = payload_of(node_run)
    pool.attempts[other_attempt.attempt_id] = payload_of(other_attempt)
    store_pg = _store(pool)
    dangling = _score(run.run_id, node_run.node_run_id, other_attempt.attempt_id)

    with pytest.raises(RunIntegrityError, match="belongs to NodeRun"):
        await store_pg.record_eval_score(dangling)

    assert not any("INSERT INTO" in sql for sql in pool.statements)


async def test_listing_reads_the_eval_table_for_that_run_and_nothing_else() -> None:
    """`list_eval_scores` serves the table's rows for exactly the named Run."""
    pool, failing = await _pool_with_spine()
    other_dimension = failing.model_copy(
        update={
            "eval_id": "eval-palette",
            "dimension_id": "palette",
            "raw_score": 0.9,
            "passed": True,
        },
        deep=True,
    )
    await _store(pool).record_eval_score(failing)
    await _store(pool).record_eval_score(other_dimension)

    listed = await _store(pool).list_eval_scores(failing.run_id)

    assert [score.eval_id for score in listed] == ["eval-contrast", "eval-palette"]
    assert listed[0].passed is False
    assert listed[1].passed is True


async def test_listing_a_run_that_does_not_exist_is_refused() -> None:
    pool, _failing = await _pool_with_spine()
    store = _store(pool)

    with pytest.raises(RunNotFound):
        await store.list_eval_scores("run-nowhere")


async def test_get_eval_score_reads_the_table_or_misses() -> None:
    pool, failing = await _pool_with_spine()
    store = _store(pool)
    await store.record_eval_score(failing)

    found = await store.get_eval_score(failing.eval_id)
    assert found == failing

    assert await store.get_eval_score("eval-nowhere") is None


async def test_deleting_a_run_takes_its_eval_rows_before_the_spine_rows() -> None:
    """The cascade order the FKs demand: eval rows, attempts, node runs, run."""
    store, run, node_run, attempt = await _spine()
    for status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.COMPLETED):
        run = await store.transition_run(run.run_id, status)
    pool = _EvalPool()
    pool.runs[run.run_id] = payload_of(run)
    pool.node_runs[node_run.node_run_id] = payload_of(node_run)
    pool.attempts[attempt.attempt_id] = payload_of(attempt)
    failing = _score(run.run_id, node_run.node_run_id, attempt.attempt_id)
    await _store(pool).record_eval_score(failing)

    assert await _store(pool).delete_run(failing.run_id) is True

    eval_index = next(
        i for i, sql in enumerate(pool.statements) if "canonical_run_eval_scores" in sql
    )
    attempts_index = next(i for i, sql in enumerate(pool.statements) if "canonical_attempts" in sql)
    node_runs_index = next(
        i for i, sql in enumerate(pool.statements) if "DELETE FROM canonical_node_runs" in sql
    )
    runs_index = next(
        i for i, sql in enumerate(pool.statements) if "DELETE FROM canonical_runs" in sql
    )
    assert eval_index < attempts_index < node_runs_index < runs_index


async def test_the_retention_purge_takes_its_eval_rows_in_the_same_transaction() -> None:
    """A purge's eval cascade carries the batch's run ids, before the spine."""
    pool, failing = await _pool_with_spine()
    pool.purge_candidates = [failing.run_id]
    store = _store(pool)

    outcome = await store.purge_expired_runs(GlobalRetentionScope(authorized_by="operator"))

    assert isinstance(outcome, PurgeOutcome)
    assert outcome.runs == 1
    assert outcome.attempts == 1
    assert outcome.node_runs == 1
    eval_index = next(
        i for i, sql in enumerate(pool.statements) if "canonical_run_eval_scores" in sql
    )
    attempts_index = next(
        i for i, sql in enumerate(pool.statements) if "DELETE FROM canonical_attempts" in sql
    )
    assert eval_index < attempts_index
    # The cascade is batch-shaped: one statement for every selected Run.
    eval_sql = pool.statements[eval_index]
    assert "ANY($1::text[])" in eval_sql
