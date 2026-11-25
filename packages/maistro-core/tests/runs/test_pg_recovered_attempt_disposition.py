"""P4a PG lock-order stand-in: Run then all NodeRuns; no Attempt locks (#232).

Real-PG races ride the shared ``spine`` fixture in
``test_recovered_attempt_disposition.py``. This file proves the statements
``PgRunStore.apply_recovered_attempt_disposition`` actually issues — without a
live database — so CI without ``MAISTRO_TEST_PG_DSN`` still gates the lock
contract.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from maistro.graph.definitions import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.evidence_json import payload_of
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


class _Row(dict):
    """asyncpg rows are mapping-like; a plain dict subclass is enough."""


class _DispositionPool:
    """Route the disposition's SQL by shape against real spine payloads."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.node_runs: dict[str, dict[str, Any]] = {}
        self.attempts: dict[str, dict[str, Any]] = {}
        self.attempt_nodes: dict[str, str] = {}
        self.node_run_runs: dict[str, str] = {}
        self.statements: list[str] = []
        self.updates: list[tuple[str, str]] = []

    def acquire(self) -> _DispositionPool:
        return self

    async def __aenter__(self) -> _DispositionPool:
        return self

    async def __aexit__(self, *_exc_info: object) -> bool:
        return False

    def transaction(self) -> _DispositionPool:
        return self

    async def fetchval(self, query: str, *args: object) -> object | None:
        sql = " ".join(query.split())
        self.statements.append(sql)
        raise AssertionError(f"unexpected fetchval query: {query!r}")

    async def fetchrow(self, query: str, *args: object) -> _Row | None:
        sql = " ".join(query.split())
        self.statements.append(sql)
        if "FROM canonical_runs WHERE run_id" in sql and "FOR UPDATE" in sql:
            payload = self.runs.get(str(args[0]))
            if payload is None:
                return None
            return _Row(run_id=str(args[0]), payload=payload, archive_key=None)
        if "FROM canonical_node_runs WHERE node_run_id" in sql:
            # Unlocked lineage read — hydrate via payload/archive_key.
            assert "FOR UPDATE" not in sql
            payload = self.node_runs.get(str(args[0]))
            if payload is None:
                return None
            return _Row(node_run_id=str(args[0]), payload=payload, archive_key=None)
        if "FROM canonical_attempts WHERE attempt_id" in sql:
            # Unlocked Attempt read — must not carry FOR UPDATE.
            assert "FOR UPDATE" not in sql, "Attempt facts must not take row locks"
            payload = self.attempts.get(str(args[0]))
            if payload is None:
                return None
            return _Row(attempt_id=str(args[0]), payload=payload, archive_key=None)
        raise AssertionError(f"unexpected fetchrow query: {query!r}")

    async def fetch(self, query: str, *args: object) -> list[_Row]:
        sql = " ".join(query.split())
        self.statements.append(sql)
        if "FROM canonical_node_runs" in sql and "FOR UPDATE" in sql:
            run_id = str(args[0])
            rows = [
                _Row(node_run_id=node_run_id, payload=payload, archive_key=None)
                for node_run_id, payload in sorted(self.node_runs.items())
                if self.node_run_runs.get(node_run_id) == run_id
            ]
            return rows
        if "FROM canonical_attempts" in sql:
            assert "FOR UPDATE" not in sql, "Attempt facts must not take row locks"
            node_ids = set(args[0]) if args else set()
            return [
                _Row(attempt_id=attempt_id, payload=payload, archive_key=None)
                for attempt_id, payload in self.attempts.items()
                if self.attempt_nodes.get(attempt_id) in node_ids
            ]
        raise AssertionError(f"unexpected fetch query: {query!r}")

    async def execute(self, query: str, *args: object) -> str:
        sql = " ".join(query.split())
        self.statements.append(sql)
        for table in ("canonical_runs", "canonical_node_runs"):
            if f"UPDATE {table}" in sql:
                # Run UPDATE binds identity at $3; NodeRun same shape.
                identity = str(args[2])
                payload = json.loads(str(args[1]))
                if table == "canonical_runs":
                    self.runs[identity] = payload
                else:
                    self.node_runs[identity] = payload
                self.updates.append((table, identity))
                return "UPDATE 1"
        raise AssertionError(f"unexpected execute query: {query!r}")


async def _disposition_pool() -> tuple[_DispositionPool, str]:
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
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(
        node_run.node_run_id, lease_holder="worker-A", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    running = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    lease = running.execution_lease
    assert lease is not None and lease.expires_at is not None
    reclaimed = await store.reclaim_expired_attempt(
        running.attempt_id, now=lease.expires_at + timedelta(seconds=1)
    )
    assert reclaimed is not None

    # Refresh after reclaim/transitions so payloads match what PG would read.
    run = await store.get_run(run.run_id)
    node_run = await store.get_node_run(node_run.node_run_id)
    assert run is not None and node_run is not None

    pool = _DispositionPool()
    pool.runs[run.run_id] = payload_of(run)
    pool.node_runs[node_run.node_run_id] = payload_of(node_run)
    pool.attempts[reclaimed.attempt_id] = payload_of(reclaimed)
    pool.attempt_nodes[reclaimed.attempt_id] = reclaimed.node_run_id
    pool.node_run_runs[node_run.node_run_id] = node_run.run_id
    return pool, reclaimed.attempt_id


def _store(pool: _DispositionPool) -> Any:
    from maistro.runs.pg_store import PgRunStore

    return PgRunStore(pool, project_store=InMemoryProjectScopeStore())  # type: ignore[arg-type]


def _first(pool: _DispositionPool, needle: str) -> int:
    return next((i for i, s in enumerate(pool.statements) if needle in s), -1)


async def test_locks_run_then_all_node_runs_without_attempt_locks() -> None:
    pool, attempt_id = await _disposition_pool()
    store = _store(pool)

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt_id)

    assert parked_node.status is RunStatus.WAITING
    assert parked_run.status is RunStatus.WAITING

    unlocked_attempt = _first(pool, "FROM canonical_attempts WHERE attempt_id")
    unlocked_node = _first(pool, "FROM canonical_node_runs WHERE node_run_id")
    run_lock = next(
        i
        for i, s in enumerate(pool.statements)
        if "FROM canonical_runs WHERE run_id" in s and "FOR UPDATE" in s
    )
    node_lock = next(
        i
        for i, s in enumerate(pool.statements)
        if "FROM canonical_node_runs" in s and "FOR UPDATE" in s
    )
    attempt_facts = next(
        i for i, s in enumerate(pool.statements) if "FROM canonical_attempts" in s and "ANY" in s
    )
    assert "FOR UPDATE" not in pool.statements[unlocked_attempt]
    assert "FOR UPDATE" not in pool.statements[unlocked_node]
    assert "FOR UPDATE" not in pool.statements[attempt_facts]
    assert unlocked_attempt < unlocked_node < run_lock < node_lock < attempt_facts
    assert pool.updates == [
        ("canonical_node_runs", parked_node.node_run_id),
        ("canonical_runs", parked_run.run_id),
    ]
    assert not any("FOR UPDATE" in s and "canonical_attempts" in s for s in pool.statements)


async def test_repeat_disposition_is_a_fixed_point_with_no_writes() -> None:
    pool, attempt_id = await _disposition_pool()
    store = _store(pool)

    await store.apply_recovered_attempt_disposition(attempt_id)
    pool.statements.clear()
    pool.updates.clear()
    # Reload parked payloads into the pool so the second call sees WAITING.
    # The first call already mutated pool.runs / pool.node_runs via execute.
    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt_id)

    assert parked_node.status is RunStatus.WAITING
    assert parked_run.status is RunStatus.WAITING
    assert pool.updates == []


async def test_lineage_reads_select_archive_key_for_hydrate() -> None:
    """Cold trees keep rows with NULL payload; disposition must ask for archive_key."""
    pool, attempt_id = await _disposition_pool()
    store = _store(pool)

    await store.apply_recovered_attempt_disposition(attempt_id)

    unlocked_node = next(
        s for s in pool.statements if "FROM canonical_node_runs WHERE node_run_id" in s
    )
    node_lock = next(
        s for s in pool.statements if "FROM canonical_node_runs" in s and "FOR UPDATE" in s
    )
    attempt_facts = next(
        s for s in pool.statements if "FROM canonical_attempts" in s and "ANY" in s
    )
    assert "archive_key" in unlocked_node
    assert "archive_key" in node_lock
    assert "archive_key" in attempt_facts


async def test_missing_node_run_row_refuses_disposition() -> None:
    """Unlocked lineage read must raise when the Attempt's NodeRun row is gone."""
    from maistro.runs.store import NodeRunNotFound

    pool, attempt_id = await _disposition_pool()
    store = _store(pool)
    # Drop the unlocked NodeRun payload; Attempt still points at it.
    node_run_id = pool.attempt_nodes[attempt_id]
    del pool.node_runs[node_run_id]

    try:
        await store.apply_recovered_attempt_disposition(attempt_id)
    except NodeRunNotFound as exc:
        assert node_run_id in str(exc)
    else:
        raise AssertionError("expected NodeRunNotFound for a missing unlocked NodeRun")


async def test_locked_set_missing_candidate_refuses_disposition() -> None:
    """FOR UPDATE set must rebind the candidate; absence is NodeRunNotFound."""
    from maistro.runs.store import NodeRunNotFound

    pool, attempt_id = await _disposition_pool()
    store = _store(pool)
    node_run_id = pool.attempt_nodes[attempt_id]
    # Unlocked read still finds the row; the locked set omits it (race / wrong run).
    pool.node_run_runs[node_run_id] = "other-run-id"

    try:
        await store.apply_recovered_attempt_disposition(attempt_id)
    except NodeRunNotFound as exc:
        assert node_run_id in str(exc)
    else:
        raise AssertionError("expected NodeRunNotFound when locked set omits the candidate")
