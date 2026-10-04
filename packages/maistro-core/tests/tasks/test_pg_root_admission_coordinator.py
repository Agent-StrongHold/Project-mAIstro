"""The PG admission coordinator's fenced decisions and joint write (#1845).

The issue's stop condition is that the admission binding and the canonical Run
become one PostgreSQL commit, and that no late owner can create, complete or
release work for a successor. These tests pin, at the coordinator's own seam
(the repo's fake-asyncpg pattern, as in ``test_idempotency_durable.py``):

- the joint write: the prepared Run's insert and the binding UPDATE happen on
  the one acquired connection, inside one READ COMMITTED transaction, insert
  before binding, exactly one pool acquisition for the whole critical section;
- the fences, checked against the locked row: fingerprint mismatch is the
  shared 409, a bound row replays without minting, an unbound row from
  another generation is refused without inserting or deleting;
- the ambiguity rule: a connection failure inside the transaction is resolved
  by rereading the durable row on a fresh connection — bound means replay,
  unbound means the error stands (the caller's release stays honest);
- the fenced release: only the caller's own unbound generation is deletable.

These are decision tests, not PG durability proof: the statement shapes are
exercised, the server's transaction semantics are not re-implemented here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from maistro.runs.admission import direct_work_graph
from maistro.runs.model import GraphSnapshot, Run, RunStatus
from maistro.runs.store import admit_in_state
from maistro.tasks.idempotency import (
    DEFAULT_REPLAY_WINDOW,
    PENDING_LEASE,
    AdmissionRecord,
    IdempotencyKeyMismatch,
)
from maistro.tasks.pg_admission import (
    AdmissionAlreadyBound,
    AdmissionBound,
    AdmissionRowMissing,
    AdmissionRowReplaced,
    PgRootAdmissionCoordinator,
)

_T0 = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
_US = 1_000_000
_T0_US = int(_T0.timestamp() * _US)
_RUN_INSERT_SQL = "INSERT INTO canonical_runs"


def _claim(
    fingerprint: str = "fp", *, task_id: str | None = None, run_id: str | None = None
) -> AdmissionRecord:
    return AdmissionRecord(
        fingerprint=fingerprint,
        request="{}",
        task_id=task_id,
        run_id=run_id,
        created_at_us=_T0_US,
        expires_at_us=_T0_US + int(DEFAULT_REPLAY_WINDOW.total_seconds()) * _US,
        lease_expires_at_us=_T0_US + int(PENDING_LEASE.total_seconds()) * _US,
    )


def _row(record: AdmissionRecord, *, scope: str = "scope") -> tuple[Any, ...]:
    return (
        scope,
        record.fingerprint,
        record.request,
        record.task_id,
        record.run_id,
        record.created_at_us,
        record.expires_at_us,
        record.lease_expires_at_us,
    )


def _successor(now_offset_seconds: int = 1) -> AdmissionRecord:
    """A takeover's row: same fingerprint, everything else re-stamped."""
    base = _claim()
    created = _T0_US + now_offset_seconds * _US
    return AdmissionRecord(
        fingerprint=base.fingerprint,
        request=base.request,
        task_id=None,
        run_id=None,
        created_at_us=created,
        expires_at_us=created + int(DEFAULT_REPLAY_WINDOW.total_seconds()) * _US,
        lease_expires_at_us=created + int(PENDING_LEASE.total_seconds()) * _US,
    )


class _Txn:
    def __init__(self, conn: _Conn, isolation: str | None) -> None:
        self._conn = conn
        self.isolation = isolation

    async def __aenter__(self) -> _Txn:
        self._conn.pool.transactions.append(self)
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _Conn:
    def __init__(self, pool: _Pool) -> None:
        self.pool = pool
        self.executes: list[tuple[str, tuple[Any, ...]]] = []
        self.fetches: list[str] = []

    def transaction(self, *, isolation: str | None = None) -> _Txn:
        return _Txn(self, isolation)

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.fetches.append(sql)
        return self.pool.row_results.pop(0)

    async def execute(self, sql: str, *args: Any) -> str:
        self.executes.append((sql, args))
        return self.pool.execute_tags.pop(0)


class _Acquire:
    def __init__(self, pool: _Pool) -> None:
        self._pool = pool

    async def __aenter__(self) -> _Conn:
        conn = _Conn(self._pool)
        self._pool.conns.append(conn)
        return conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _Pool:
    """asyncpg at the coordinator's boundary: one fresh connection per
    acquire, queued results, and the transaction/isolation record."""

    def __init__(self) -> None:
        self.row_results: list[Any] = []
        self.execute_tags: list[str] = []
        self.conns: list[_Conn] = []
        self.transactions: list[_Txn] = []

    def acquire(self) -> _Acquire:
        return _Acquire(self)


class _Inserts:
    """The injected connection-owned insert callback, recording its order."""

    def __init__(self) -> None:
        self.runs: list[Run] = []
        self.conns: list[Any] = []
        self.raise_after: int | None = None

    async def __call__(self, conn: Any, run: Run) -> None:
        self.conns.append(conn)
        self.runs.append(run)
        await conn.execute(_RUN_INSERT_SQL, run.run_id)
        if self.raise_after is not None and len(self.runs) > self.raise_after:
            raise asyncpg.InterfaceError("connection lost mid-write")


async def _prepared_run() -> Run:
    graph = direct_work_graph(
        workspace_id="ws",
        project_id="proj",
        node_type="llm.summarize",
        name="n",
        parameters={},
        description="d",
    )
    run = Run(
        workspace_id="ws",
        project_id="proj",
        graph=GraphSnapshot.from_graph(graph),
        actor_principal_id="user-1",
        provenance={},
    )
    # The prepare half's contract: the Run arrives with its initial state
    # already decided, as PgRunStore.prepare_run leaves it.
    return admit_in_state(run, RunStatus.QUEUED)


async def _bind(pool: _Pool, claim: AdmissionRecord, **kw: Any) -> Any:
    inserts = kw.pop("inserts", None) or _Inserts()
    coordinator = PgRootAdmissionCoordinator(pool, insert_run=inserts)
    outcome = await coordinator.bind_admission(
        scope_key=kw.pop("scope_key", "scope"),
        claim=claim,
        task_id=kw.pop("task_id", "t1"),
        prepare_run=kw.pop("prepare", _prepared_run),
    )
    return outcome, inserts


async def test_the_run_insert_and_the_binding_are_one_transaction_one_connection() -> None:
    pool = _Pool()
    pool.row_results.append(_row(_claim()))
    pool.execute_tags.append("INSERT 0 1")  # canonical_runs
    pool.execute_tags.append("UPDATE 1")  # the binding

    outcome, inserts = await _bind(pool, _claim())

    assert isinstance(outcome, AdmissionBound)
    assert outcome.task_id == "t1"
    assert outcome.run_id == outcome.record.run_id
    assert outcome.record.task_id == "t1"
    # Frozen decision, after the fact, and honest about the original claim.
    assert outcome.record.created_at_us == _T0_US
    assert outcome.record.expires_at_us == _T0_US + int(DEFAULT_REPLAY_WINDOW.total_seconds()) * _US
    # One acquisition, one transaction, READ COMMITTED, row lock first.
    assert len(pool.conns) == 1
    (txn,) = pool.transactions
    assert txn.isolation == "read_committed"
    conn = pool.conns[0]
    assert "FOR UPDATE" in conn.fetches[0]
    # Insert and binding on the same connection, in that order.
    assert inserts.conns == [conn]
    assert conn.executes[0][0] == _RUN_INSERT_SQL
    assert conn.executes[1][0].strip().startswith("UPDATE task_idempotency")
    assert conn.executes[1][1] == ("scope", "t1", outcome.run_id)


async def test_a_bound_row_replays_without_minting() -> None:
    pool = _Pool()
    pool.row_results.append(_row(_claim(task_id="t9", run_id="r9")))

    outcome, inserts = await _bind(pool, _claim())

    assert isinstance(outcome, AdmissionAlreadyBound)
    assert outcome.record.task_id == "t9"
    assert outcome.record.run_id == "r9"
    assert inserts.runs == []  # one Run is necessary; a second is forbidden
    assert all(sql.startswith("UPDATE") is False for sql, _ in pool.conns[0].executes)


async def test_a_fingerprint_mismatch_is_the_scope_409() -> None:
    pool = _Pool()
    pool.row_results.append(_row(_claim(fingerprint="other-payload")))

    with pytest.raises(IdempotencyKeyMismatch):
        await _bind(pool, _claim(fingerprint="fp"))
    assert pool.conns[0].executes == []  # nothing written under a foreign claim


async def test_a_replaced_generation_neither_inserts_nor_deletes() -> None:
    pool = _Pool()
    pool.row_results.append(_row(_successor()))

    outcome, inserts = await _bind(pool, _claim())

    assert isinstance(outcome, AdmissionRowReplaced)
    assert outcome.record.created_at_us != _T0_US
    assert inserts.runs == []
    assert all(sql.startswith("DELETE") is False for sql, _ in pool.conns[0].executes)


async def test_a_missing_row_sends_the_caller_back_to_claim() -> None:
    pool = _Pool()
    pool.row_results.append(None)

    outcome, inserts = await _bind(pool, _claim())

    assert isinstance(outcome, AdmissionRowMissing)
    assert inserts.runs == []


async def test_an_ambiguous_commit_rereads_and_replays_when_bound() -> None:
    pool = _Pool()
    inserts = _Inserts()
    inserts.raise_after = 0  # the write lands, then the connection dies
    pool.row_results.append(_row(_claim()))
    pool.execute_tags.append("INSERT 0 1")
    # The fresh-connection reread finds the generation bound: it committed.
    pool.row_results.append(_row(_claim(task_id="t1", run_id="r-atomic")))

    outcome, _ = await _bind(pool, _claim(), inserts=inserts)

    assert isinstance(outcome, AdmissionAlreadyBound)
    assert outcome.record.run_id == "r-atomic"
    assert len(pool.conns) == 2  # the reread is a new connection


async def test_an_ambiguous_commit_with_an_unbound_row_reraises() -> None:
    pool = _Pool()
    inserts = _Inserts()
    inserts.raise_after = 0
    pool.row_results.append(_row(_claim()))
    pool.execute_tags.append("INSERT 0 1")
    # The reread finds the row unbound: nothing was admitted, the error stands.
    pool.row_results.append(_row(_claim()))

    with pytest.raises(asyncpg.InterfaceError):
        await _bind(pool, _claim(), inserts=inserts)


async def test_a_preparation_failure_never_opens_the_transaction() -> None:
    pool = _Pool()

    async def refuses() -> Run:
        raise ValueError("project scope refused")

    coordinator = PgRootAdmissionCoordinator(pool, insert_run=_Inserts())
    with pytest.raises(ValueError):
        await coordinator.bind_admission(
            scope_key="scope",
            claim=_claim(),
            task_id="t1",
            prepare_run=refuses,
        )
    assert pool.transactions == [] and pool.conns == []


async def test_release_claim_is_fenced_to_the_callers_own_generation() -> None:
    pool = _Pool()
    coordinator = PgRootAdmissionCoordinator(pool, insert_run=_Inserts())

    pool.execute_tags.append("DELETE 1")
    assert await coordinator.release_claim("scope", _claim()) is True
    sql, args = pool.conns[0].executes[0]
    assert sql.strip().startswith("DELETE FROM task_idempotency")
    assert "task_id IS NULL" in sql
    assert args == ("scope", _T0_US, _T0_US + int(PENDING_LEASE.total_seconds()) * _US)

    pool.execute_tags.append("DELETE 0")
    assert await coordinator.release_claim("scope", _claim()) is False


async def test_the_fenced_release_refuses_a_superseded_generation() -> None:
    """A late owner holding pre-takeover values cannot delete the successor's
    fresh claim: the fence compares the stored generation, not just the key."""
    pool = _Pool()
    coordinator = PgRootAdmissionCoordinator(pool, insert_run=_Inserts())
    successor = _successor()
    # The row now holds the successor's stamps; the late owner passes its own.
    pool.row_results.append(_row(successor))

    # The DELETE's WHERE clause is the fence: with the successor's stamps
    # stored, the late owner's values match nothing, so the tag reports 0.
    pool.execute_tags.append("DELETE 0")
    assert await coordinator.release_claim("scope", _claim()) is False


async def test_the_binding_does_not_refresh_the_replay_window() -> None:
    """A takeover rotates ownership only; the window the claim was granted is
    the window the binding keeps."""
    pool = _Pool()
    grant = _successor(now_offset_seconds=60)
    pool.row_results.append(_row(grant))
    pool.execute_tags.append("INSERT 0 1")
    pool.execute_tags.append("UPDATE 1")

    outcome, _ = await _bind(pool, grant)

    assert isinstance(outcome, AdmissionBound)
    assert outcome.record.expires_at_us == grant.expires_at_us
    assert outcome.record.created_at_us == grant.created_at_us
    assert outcome.record.lease_expires_at_us == grant.lease_expires_at_us


async def test_a_prepared_run_enters_the_insert_as_queued() -> None:
    """The canonical Run reaches the insert callback with its initial state
    already decided — QUEUED for task admission — and its provenance intact."""
    pool = _Pool()
    pool.row_results.append(_row(_claim()))
    pool.execute_tags.append("INSERT 0 1")
    pool.execute_tags.append("UPDATE 1")

    outcome, inserts = await _bind(pool, _claim())

    assert isinstance(outcome, AdmissionBound)
    (run,) = inserts.runs
    assert run.status is RunStatus.QUEUED
    assert run.actor_principal_id == "user-1"
