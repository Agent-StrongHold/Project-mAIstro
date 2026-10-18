"""Generation coordination through the real adapter/Run store and fake asyncpg.

The fake owns durable rows and transaction-local copies: failed transactions
really discard BOTH writes, rather than returning a scripted successful claim.
It records connection lifetimes and can lose a COMMIT response before or after
applying the transaction. This is not PostgreSQL, replica, or process-kill proof.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission_identity import (
    Acknowledged,
    AdmissionBinding,
    AlreadyAcknowledged,
    AlreadyBound,
    BindingMismatch,
    Claimed,
    Pending,
    Released,
    Replayed,
    RootAdmissionEnvelope,
    RootAdmissionResult,
    StaleOwner,
)
from maistro.runs.concurrency import RunConcurrencyExceeded, RunConcurrencyLimits
from maistro.runs.consumer_claim import ClaimingPgRunStore
from maistro.runs.model import GraphSnapshot, Run, RunStatus
from maistro.runs.pg_store import PgRunStore
from maistro.runs.store import ArchivedPayloadUnavailable, RunIntegrityError, RunNotFound
from maistro.tasks.admission import build_root_admission_envelope, prepare_task_root
from maistro.tasks.idempotency import IdempotencyKeyMismatch
from maistro.tasks.models import TaskCreate
from maistro.tasks.pg_admission import PgRootAdmissionCoordinator

_T0 = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)


def _sql(sql: str) -> str:
    return " ".join(sql.split())


def _value(expression: str, args: tuple[Any, ...]) -> Any:
    expression = expression.strip()
    match = re.match(r"\$(\d+)", expression)
    if match:
        return args[int(match[1]) - 1]
    if expression.upper() == "NULL":
        return None
    if expression.isdecimal():
        return int(expression)
    raise AssertionError(f"Unsupported fake SQL value: {expression}")


class _Transaction:
    def __init__(self, conn: _Connection, isolation: str | None) -> None:
        self.conn = conn
        self.isolation = isolation

    async def __aenter__(self) -> _Transaction:
        assert not self.conn.in_transaction
        self.conn.in_transaction = True
        self.conn.rows = deepcopy(self.conn.pool.rows)
        self.conn.runs = deepcopy(self.conn.pool.runs)
        self.conn.pool.events.append((self.conn.number, "begin", self.isolation))
        return self

    async def __aexit__(self, kind: Any, exc: Any, tb: Any) -> bool:
        conn, pool = self.conn, self.conn.pool
        mode = (
            pool.commit_faults.pop(0)
            if kind is None and conn.wrote_run and pool.commit_faults
            else None
        )
        committed = kind is None and mode not in {"before", "cancel_before"}
        if committed:
            pool.rows, pool.runs = conn.rows, conn.runs
        pool.events.append((conn.number, "commit" if committed else "rollback", mode))
        conn.in_transaction = False
        if mode:
            if pool.after_commit_fault is not None:
                pool.after_commit_fault(pool)
            if mode.startswith("cancel"):
                raise asyncio.CancelledError
            raise pool.commit_error_type("injected lost COMMIT response")
        return False


class _Connection:
    def __init__(self, pool: TransactionalPool, number: int) -> None:
        self.pool, self.number = pool, number
        self.in_transaction = False
        self.rows: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.wrote_run = False

    def transaction(self, *, isolation: str | None = None) -> _Transaction:
        return _Transaction(self, isolation)

    def _record(self, sql: str, args: tuple[Any, ...]) -> str:
        sql = _sql(sql)
        self.pool.events.append((self.number, sql, args))
        return sql

    def _tables(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        return (self.rows, self.runs) if self.in_transaction else (self.pool.rows, self.pool.runs)

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        sql = self._record(sql, args)
        rows, runs = self._tables()
        if sql.startswith("INSERT INTO task_idempotency"):
            return self._insert_claim(sql, args)
        if "FROM task_idempotency" in sql:
            assert self.in_transaction, "admission reads must own a transaction"
            assert "FOR UPDATE" in sql, "admission reads must lock current evidence"
            if self.pool.on_locked_read is not None:
                callback, self.pool.on_locked_read = self.pool.on_locked_read, None
                callback(self)
            return deepcopy(rows.get(args[0]))
        if "workspace_active" in sql:
            active = [
                r
                for r in runs.values()
                if r["status"] in {"created", "queued", "running"} and r["parent_run_id"] is None
            ]
            return {
                "workspace_active": sum(r["workspace_id"] == args[0] for r in active),
                "principal_active": sum(
                    r["payload"]["actor_principal_id"] == args[1] for r in active
                ),
            }
        if "FROM canonical_runs" in sql and "WHERE run_id = $1" in sql:
            return deepcopy(runs.get(args[0]))
        raise AssertionError(f"Unsupported fetchrow: {sql}")

    async def fetchval(self, sql: str, *args: Any) -> Any:
        sql = self._record(sql, args)
        if sql.startswith("INSERT INTO task_idempotency"):
            row = self._insert_claim(sql, args)
            return row["scope_key"] if row is not None else None
        raise AssertionError(f"Unsupported fetchval: {sql}")

    def _insert_claim(self, sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        assert self.in_transaction
        match = re.search(r"INSERT INTO task_idempotency\s*\((.*?)\) VALUES\s*\((.*?)\)", sql)
        assert match, sql
        columns = [s.strip() for s in match[1].split(",")]
        values = [_value(s, args) for s in match[2].split(",")]
        row = dict(zip(columns, values, strict=True))
        row.setdefault("completed_at", 0)
        row.setdefault("task_id", None)
        row.setdefault("run_id", None)
        row.setdefault("acknowledged_at", None)
        if self.pool.on_insert_conflict is not None:
            callback, self.pool.on_insert_conflict = self.pool.on_insert_conflict, None
            callback(self, row)
            return None
        if row["scope_key"] in self.rows:
            return None
        self.rows[row["scope_key"]] = row
        return deepcopy(row)

    async def execute(self, sql: str, *args: Any) -> str:
        sql = self._record(sql, args)
        rows, runs = self._tables()
        if sql.startswith("SELECT pg_advisory_xact_lock"):
            assert self.in_transaction
            assert any(
                n == self.number and "FOR UPDATE" in statement
                for n, statement, _ in self.pool.events
            ), "admission row lock must precede root capacity locks"
            return "SELECT 1"
        if sql.startswith("INSERT INTO canonical_runs"):
            assert self.in_transaction
            if args[0] in runs:
                raise asyncpg.UniqueViolationError("duplicate run")
            runs[args[0]] = {
                "run_id": args[0],
                "workspace_id": args[1],
                "project_id": args[2],
                "parent_run_id": args[3],
                "parent_node_run_id": args[4],
                "status": args[5],
                "payload": json.loads(args[6]),
                "archive_key": None,
            }
            self.wrote_run = True
            if self.pool.after_run_insert is not None:
                self.pool.after_run_insert(self)
            return "INSERT 0 1"
        if sql.startswith("INSERT INTO task_idempotency"):
            return "INSERT 0 1" if self._insert_claim(sql, args) is not None else "INSERT 0 0"
        if sql.startswith("UPDATE task_idempotency"):
            assert self.in_transaction
            row = rows.get(args[0])
            if row is None:
                return "UPDATE 0"
            set_clause = sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            for assignment in set_clause.split(","):
                column, expression = assignment.split("=", 1)
                row[column.strip()] = _value(expression, args)
            return "UPDATE 1"
        if sql.startswith("DELETE FROM task_idempotency"):
            return self._delete_claim(sql, args)
        raise AssertionError(f"Unsupported execute: {sql}")

    def _delete_claim(self, sql: str, args: tuple[Any, ...]) -> str:
        assert self.in_transaction
        rows, _ = self._tables()
        if "SKIP LOCKED" not in sql:
            return f"DELETE {int(rows.pop(args[0], None) is not None)}"
        assert "format_version IN (1, 2)" in sql
        assert "scope_key ~ '^[0-9a-f]{64}$'" in sql
        assert "fingerprint ~ '^[0-9a-f]{64}$'" in sql
        if self.pool.purge_error is not None:
            raise self.pool.purge_error
        selected = [
            row
            for row in rows.values()
            if row["expires_at"] <= args[0]
            and row["scope_key"] != args[2]
            and row["format_version"] in (1, 2)
            and re.fullmatch(r"[0-9a-f]{64}", row["scope_key"])
            and re.fullmatch(r"[0-9a-f]{64}", row["fingerprint"])
        ]
        selected.sort(key=lambda row: (row["created_at"], row["scope_key"]))
        for row in selected[: args[1]]:
            del rows[row["scope_key"]]
        return f"DELETE {min(len(selected), args[1])}"

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        sql = self._record(sql, args)
        if "SKIP LOCKED" in sql and "task_idempotency" in sql:
            # Housekeeping shape is pinned by its dedicated tests below.
            return []
        if "FROM canonical_runs WHERE status = $1" in sql:
            _, runs = self._tables()
            selected = [r for r in runs.values() if r["status"] == args[0]]
            if "admission_source" in sql:
                selected = [
                    r
                    for r in selected
                    if r["payload"]["provenance"].get("admission_source") == args[1]
                ]
            return deepcopy(selected[: args[-2]])
        raise AssertionError(f"Unsupported fetch: {sql}")


class _Acquire:
    def __init__(self, pool: TransactionalPool) -> None:
        self.pool = pool
        self.conn: _Connection | None = None

    async def __aenter__(self) -> _Connection:
        pool = self.pool
        assert pool.owner is not asyncio.current_task(), (
            "nested acquire would deadlock a size-one pool"
        )
        await pool.slot.acquire()
        if pool.next_acquire_error is not None:
            exc, pool.next_acquire_error = pool.next_acquire_error, None
            pool.slot.release()
            raise exc
        pool.owner = asyncio.current_task()
        self.conn = _Connection(pool, len(pool.connections) + 1)
        pool.connections.append(self.conn)
        pool.events.append((self.conn.number, "acquire", ()))
        return self.conn

    async def __aexit__(self, *exc: Any) -> bool:
        assert self.conn is not None
        assert not self.conn.in_transaction
        self.pool.events.append((self.conn.number, "release", ()))
        self.pool.owner = None
        self.pool.slot.release()
        return False


class TransactionalPool:
    """A size-one transport double; use production APIs above this boundary."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.slot = asyncio.Semaphore(1)
        self.owner: asyncio.Task[Any] | None = None
        self.connections: list[_Connection] = []
        self.events: list[tuple[int, str, Any]] = []
        self.commit_faults: list[str] = []
        self.commit_error_type: type[Exception] = asyncpg.InterfaceError
        self.after_commit_fault: Callable[[TransactionalPool], None] | None = None
        self.after_run_insert: Callable[[_Connection], None] | None = None
        self.on_locked_read: Callable[[_Connection], None] | None = None
        self.on_insert_conflict: Callable[[_Connection, dict[str, Any]], None] | None = None
        self.next_acquire_error: BaseException | None = None
        self.purge_error: Exception | None = None

    def acquire(self) -> _Acquire:
        return _Acquire(self)


@dataclass
class Harness:
    pool: TransactionalPool
    store: PgRunStore
    coordinator: PgRootAdmissionCoordinator
    project_id: str
    now: datetime = _T0
    prepared: int = 0
    hydrated: int = 0
    preparation_error: BaseException | None = None
    hydration_error: BaseException | None = None
    before_prepare: Callable[[Harness], None] | None = None

    def deadline(self) -> float:
        return asyncio.get_running_loop().time() + 5

    def candidate(
        self, *, description: str = "original", key: str = "key", **overrides: Any
    ) -> RootAdmissionEnvelope:
        fields = {
            "workspace_id": "ws",
            "project_id": self.project_id,
            "generation_id": uuid4(),
            "receipt_id": uuid4().hex[:12],
            "created_at": self.now,
            "origin_principal_id": "origin",
            "explicit_key": key,
            "service_principal_id": "service",
            "delegation_id": "delegation",
            "actor_kind": "service",
            "request_id": "request-original",
        }
        fields.update(overrides)
        return build_root_admission_envelope(TaskCreate(description=description), **fields)

    async def prepare(self, envelope: RootAdmissionEnvelope) -> Run:
        assert self.pool.owner is not asyncio.current_task(), (
            "preparation must finish outside acquired connection"
        )
        self.prepared += 1
        if self.before_prepare is not None:
            self.before_prepare(self)
        if self.preparation_error is not None:
            raise self.preparation_error
        return await prepare_task_root(envelope, prepare_root_run=self.store.prepare_root_run)

    async def hydrate(self, run_id: str) -> Run | None:
        assert self.pool.owner is not asyncio.current_task(), (
            "hydration must happen after releasing admission connection"
        )
        self.hydrated += 1
        if self.hydration_error is not None:
            raise self.hydration_error
        return await self.store.get_run(run_id)


async def make_harness(*, limit: int = 32) -> Harness:
    pool = TransactionalPool()
    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("ws")
    store = ClaimingPgRunStore(
        pool,
        project_store=projects,
        concurrency_limits=RunConcurrencyLimits(per_principal=limit, per_workspace=limit),
    )
    # Bind production callback wrappers only after the harness exists.
    harness = Harness(pool, store, None, project.project_id)  # type: ignore[arg-type]
    harness.coordinator = PgRootAdmissionCoordinator(
        pool,
        insert_run=store.insert_prepared_run,
        prepare=harness.prepare,
        get_run=harness.hydrate,
        utc_clock=lambda: harness.now,
    )
    return harness


async def claim(h: Harness, candidate: RootAdmissionEnvelope | None = None) -> Claimed:
    result = await h.coordinator.claim(candidate or h.candidate(), deadline=h.deadline())
    assert isinstance(result, Claimed)
    return result


async def admit(h: Harness, claimed: Claimed) -> RootAdmissionResult:
    result = await h.coordinator.admit(
        claimed.ticket, claimed.record.envelope, deadline=h.deadline()
    )
    assert isinstance(result, RootAdmissionResult)
    return result


async def test_claim_returns_the_persisted_generation_and_independent_owner() -> None:
    h = await make_harness()
    candidate = h.candidate()
    first = await claim(h, candidate)
    assert first.record.envelope == candidate
    assert first.ticket.generation_id == candidate.generation_id
    assert first.ticket.owner_token != candidate.generation_id
    assert first.record.owns(first.ticket)
    assert len(h.pool.rows) == 1 and not h.pool.runs
    assert h.prepared == h.hydrated == 0
    pending = await h.coordinator.claim(h.candidate(request_id="retry"), deadline=h.deadline())
    assert isinstance(pending, Pending)
    assert pending.record == first.record


async def test_takeover_rotates_owner_without_refreshing_any_original_identity() -> None:
    h = await make_harness()
    first = await claim(h)
    h.now += timedelta(seconds=30)
    retry = h.candidate(project_id="later-project", request_id="later-request")
    second = await claim(h, retry)
    assert second.record.envelope == first.record.envelope
    assert second.ticket.generation_id == first.ticket.generation_id
    assert second.ticket.owner_token != first.ticket.owner_token
    assert second.record.lease_expires_at_us == int(h.now.timestamp() * 1_000_000) + 30_000_000
    assert h.prepared == 0


async def test_inclusive_expiry_replaces_generation_before_payload_mismatch_or_snapshot_decode() -> (
    None
):
    h = await make_harness()
    first = await claim(h)
    h.pool.rows[first.ticket.scope_key]["request"] = "malformed expired snapshot"
    h.now += timedelta(hours=24)
    candidate = h.candidate(description="new generation")
    second = await claim(h, candidate)
    assert second.record.envelope == candidate
    assert second.ticket.generation_id != first.ticket.generation_id
    assert len(h.pool.rows) == 1


async def test_unexpired_mismatch_wins_before_invalid_snapshot() -> None:
    h = await make_harness()
    first = await claim(h)
    h.pool.rows[first.ticket.scope_key]["request"] = "malformed snapshot"
    with pytest.raises(IdempotencyKeyMismatch):
        await h.coordinator.claim(h.candidate(description="different"), deadline=h.deadline())
    assert not h.pool.runs and len(h.pool.rows) == 1


async def test_unknown_format_cannot_be_deleted_even_after_expiry() -> None:
    from maistro.tasks.admission_codec import AdmissionDecodeCode, AdmissionRowDecodeError

    h = await make_harness()
    first = await claim(h)
    h.pool.rows[first.ticket.scope_key]["format_version"] = 99
    original = deepcopy(h.pool.rows)
    h.now += timedelta(hours=24)
    with pytest.raises(AdmissionRowDecodeError) as error:
        await h.coordinator.claim(h.candidate(), deadline=h.deadline())
    assert error.value.code is AdmissionDecodeCode.UNSUPPORTED_FORMAT
    assert h.pool.rows == original


async def test_atomic_commit_inserts_run_then_binding_before_hydration() -> None:
    h = await make_harness()
    first = await claim(h)
    result = await admit(h, first)
    assert result.created is True
    assert result.receipt_id == first.record.envelope.receipt_id
    row = h.pool.rows[first.ticket.scope_key]
    assert row["run_id"] == result.run_id
    assert row["task_id"] == result.receipt_id
    assert row["acknowledged_at"] is None
    assert len(h.pool.runs) == 1 and h.prepared == h.hydrated == 1
    writes = [
        (n, sql)
        for n, sql, _ in h.pool.events
        if sql.startswith(("INSERT INTO canonical_runs", "UPDATE task_idempotency SET task_id"))
    ]
    assert len(writes) == 2 and writes[0][0] == writes[1][0]
    assert all(
        isolation == "read_committed"
        for _, operation, isolation in h.pool.events
        if operation == "begin"
    )
    run = Run.model_validate_json(result.run_snapshot.text)
    assert run.status is RunStatus.QUEUED
    assert run.project_id == first.record.envelope.project_id
    assert run.provenance["request_id"] == "request-original"


async def test_failure_after_run_insert_rolls_back_run_and_binding_together() -> None:
    h = await make_harness()
    first = await claim(h)
    original = deepcopy(h.pool.rows)

    def fail(_conn: _Connection) -> None:
        raise RuntimeError("injected after INSERT before binding")

    h.pool.after_run_insert = fail
    with pytest.raises(RuntimeError, match="after INSERT"):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert h.pool.rows == original
    assert h.pool.runs == {}
    assert h.hydrated == 0 and h.pool.owner is None


@pytest.mark.parametrize("mode,expected_created", [("after", False), ("before", True)])
@pytest.mark.parametrize("error_type", [asyncpg.InterfaceError, ConnectionResetError])
async def test_unknown_commit_uses_new_locked_connection_and_preserves_one_run(
    mode: str, expected_created: bool, error_type: type[Exception]
) -> None:
    h = await make_harness()
    first = await claim(h)
    h.pool.commit_faults = [mode]
    h.pool.commit_error_type = error_type
    result = await admit(h, first)
    assert result.created is expected_created
    assert h.prepared == 1
    assert len(h.pool.runs) == 1
    assert h.pool.rows[first.ticket.scope_key]["run_id"] == result.run_id
    fault_index = next(
        i
        for i, (_, operation, detail) in enumerate(h.pool.events)
        if operation in {"commit", "rollback"} and detail == mode
    )
    writer = h.pool.events[fault_index][0]
    after = h.pool.events[fault_index + 1 :]
    assert after[0] == (writer, "release", ())
    resolver = next(n for n, operation, _ in after if operation == "acquire")
    assert resolver != writer
    assert any(n == resolver and "FOR UPDATE" in operation for n, operation, _ in after)
    inserted_ids = [
        args[0] for _, sql, args in h.pool.events if sql.startswith("INSERT INTO canonical_runs")
    ]
    assert len(set(inserted_ids)) == 1, "known rollback must retry the same private Run"


async def test_second_transport_outage_preserves_unresolved_generation() -> None:
    h = await make_harness()
    first = await claim(h)
    h.pool.commit_faults = ["after"]
    h.pool.after_commit_fault = lambda pool: setattr(
        pool, "next_acquire_error", asyncpg.InterfaceError("second outage")
    )
    with pytest.raises(asyncpg.InterfaceError, match="second outage"):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert len(h.pool.runs) == len(h.pool.rows) == 1
    assert h.pool.rows[first.ticket.scope_key]["run_id"] in h.pool.runs
    assert not any(sql.startswith("DELETE") for _, sql, _ in h.pool.events)
    assert h.pool.owner is None


@pytest.mark.parametrize("mode,run_count", [("cancel_before", 0), ("cancel_after", 1)])
async def test_cancellation_propagates_and_never_erases_durable_evidence(
    mode: str, run_count: int
) -> None:
    h = await make_harness()
    first = await claim(h)
    h.pool.commit_faults = [mode]
    with pytest.raises(asyncio.CancelledError):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert len(h.pool.rows) == 1
    assert len(h.pool.runs) == run_count
    assert h.pool.owner is None
    assert not any(sql.startswith("DELETE") for _, sql, _ in h.pool.events)


async def test_stale_owner_cannot_admit_acknowledge_or_release_successor() -> None:
    h = await make_harness()
    first = await claim(h)
    h.now += timedelta(seconds=30)
    second = await claim(h)
    original = deepcopy(h.pool.rows)
    assert isinstance(
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline()),
        StaleOwner,
    )
    assert isinstance(
        await h.coordinator.complete(
            first.ticket,
            AdmissionBinding("imaginary", first.record.envelope.receipt_id),
            deadline=h.deadline(),
        ),
        StaleOwner,
    )
    assert isinstance(await h.coordinator.release(first.ticket, deadline=h.deadline()), StaleOwner)
    assert h.pool.rows == original and h.pool.runs == {} and h.prepared == 0
    result = await admit(h, second)
    replay = await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert isinstance(replay, RootAdmissionResult) and replay.run_id == result.run_id
    assert replay.created is False


async def test_generation_fence_is_independent_even_if_owner_value_is_reused() -> None:
    h = await make_harness()
    first = await claim(h)
    wrong = replace(first.ticket, generation_id=uuid4())
    original = deepcopy(h.pool.rows)
    assert isinstance(await h.coordinator.release(wrong, deadline=h.deadline()), StaleOwner)
    assert isinstance(
        await h.coordinator.admit(wrong, first.record.envelope, deadline=h.deadline()), StaleOwner
    )
    assert h.pool.rows == original and not h.pool.runs


async def test_complete_only_acknowledges_existing_identical_binding_once() -> None:
    h = await make_harness()
    first = await claim(h)
    binding = AdmissionBinding("not-yet-inserted", first.record.envelope.receipt_id)
    assert isinstance(
        await h.coordinator.complete(first.ticket, binding, deadline=h.deadline()), BindingMismatch
    )
    result = await admit(h, first)
    binding = AdmissionBinding(result.run_id, result.receipt_id)
    before = deepcopy(h.pool.rows[first.ticket.scope_key])
    assert isinstance(
        await h.coordinator.complete(
            first.ticket, replace(binding, run_id="different"), deadline=h.deadline()
        ),
        BindingMismatch,
    )
    assert isinstance(
        await h.coordinator.complete(first.ticket, binding, deadline=h.deadline()), Acknowledged
    )
    acknowledged = deepcopy(h.pool.rows[first.ticket.scope_key])
    h.now += timedelta(seconds=1)
    assert isinstance(
        await h.coordinator.complete(first.ticket, binding, deadline=h.deadline()),
        AlreadyAcknowledged,
    )
    assert h.pool.rows[first.ticket.scope_key] == acknowledged
    assert {k: v for k, v in acknowledged.items() if k != "acknowledged_at"} == {
        k: v for k, v in before.items() if k != "acknowledged_at"
    }
    assert isinstance(
        await h.coordinator.release(first.ticket, deadline=h.deadline()), AlreadyBound
    )


async def test_owned_unbound_release_is_the_only_successful_release() -> None:
    h = await make_harness()
    first = await claim(h)
    assert isinstance(await h.coordinator.release(first.ticket, deadline=h.deadline()), Released)
    assert h.pool.rows == {}
    assert isinstance(await h.coordinator.release(first.ticket, deadline=h.deadline()), StaleOwner)


async def test_capacity_refusal_rolls_back_run_then_releases_only_proven_unbound_claim() -> None:
    h = await make_harness(limit=1)
    await admit(h, await claim(h, h.candidate(key="first")))
    second = await claim(h, h.candidate(key="second"))
    with pytest.raises(RunConcurrencyExceeded):
        await h.coordinator.admit(second.ticket, second.record.envelope, deadline=h.deadline())
    assert len(h.pool.runs) == len(h.pool.rows) == 1
    assert second.ticket.scope_key not in h.pool.rows
    assert isinstance(
        await h.coordinator.claim(h.candidate(key="second"), deadline=h.deadline()), Claimed
    )


async def test_bound_replay_at_capacity_skips_prepare_and_new_root_capacity() -> None:
    h = await make_harness(limit=1)
    first = await claim(h)
    original = await admit(h, first)
    h.preparation_error = AssertionError("bound replay must not prepare")
    h.now += timedelta(seconds=31)
    outcome = await h.coordinator.claim(h.candidate(request_id="retry"), deadline=h.deadline())
    assert isinstance(outcome, Replayed)
    result = await h.coordinator.replay(
        outcome.record, origin_principal_id="origin", workspace_id="ws", deadline=h.deadline()
    )
    assert result.run_id == original.run_id and result.receipt_id == original.receipt_id
    assert result.created is False and len(h.pool.runs) == 1
    assert h.prepared == 1


@pytest.mark.parametrize(
    "error", [ValueError("scope refused"), RuntimeError("preparation refused")]
)
async def test_definitive_preparation_refusal_releases_without_inserting(error: Exception) -> None:
    h = await make_harness()
    first = await claim(h)
    h.preparation_error = error
    with pytest.raises(type(error)):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert not h.pool.rows and not h.pool.runs


@pytest.mark.parametrize(
    "error",
    [
        asyncpg.InterfaceError("prepare transport"),
        ConnectionRefusedError("preparation reconnect failed"),
        asyncio.CancelledError(),
    ],
)
async def test_uncertain_preparation_or_cancellation_preserves_claim(error: BaseException) -> None:
    h = await make_harness()
    first = await claim(h)
    h.preparation_error = error
    with pytest.raises(type(error)):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert len(h.pool.rows) == 1 and not h.pool.runs

    assert not any(sql.startswith("DELETE") for _, sql, _ in h.pool.events)


async def test_hydration_failure_after_commit_never_releases_or_mints_replacement() -> None:
    h = await make_harness()
    first = await claim(h)
    h.hydration_error = asyncpg.InterfaceError("archive unavailable")
    with pytest.raises(asyncpg.InterfaceError, match="archive unavailable"):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert len(h.pool.rows) == len(h.pool.runs) == 1
    h.hydration_error = None
    replay = await h.coordinator.claim(h.candidate(), deadline=h.deadline())
    assert isinstance(replay, Replayed)
    result = await h.coordinator.replay(
        replay.record, origin_principal_id="origin", workspace_id="ws", deadline=h.deadline()
    )
    assert result.run_id in h.pool.runs and not result.created
    assert h.prepared == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_id", "foreign"),
        ("project_id", "foreign"),
        ("actor_principal_id", "foreign"),
        ("parent_run_id", "foreign"),
    ],
)
async def test_canonical_binding_rejects_wrong_original_identity(field: str, value: str) -> None:
    h = await make_harness()
    first = await claim(h)
    result = await admit(h, first)
    payload = h.pool.runs[result.run_id]["payload"]
    payload[field] = value
    if field in {"workspace_id", "project_id"}:
        graph = GraphSnapshot.model_validate(payload["graph"]).materialize()
        graph = graph.model_copy(update={field: value})
        payload["graph"] = GraphSnapshot.from_graph(graph).model_dump(mode="json")
    Run.model_validate(payload)
    with pytest.raises(RunIntegrityError):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert len(h.pool.runs) == 1 and h.prepared == 1


async def test_missing_canonical_run_does_not_replace_live_generation() -> None:
    h = await make_harness()
    first = await claim(h)
    result = await admit(h, first)
    del h.pool.runs[result.run_id]
    with pytest.raises(RunNotFound):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert not h.pool.runs and len(h.pool.rows) == 1
    assert h.prepared == 1


async def test_deadline_timeout_during_preparation_preserves_original_generation() -> None:
    h = await make_harness()
    first = await claim(h)
    started = asyncio.Event()

    async def blocked(_envelope: RootAdmissionEnvelope) -> Run:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    h.coordinator = PgRootAdmissionCoordinator(
        h.pool,
        insert_run=h.store.insert_prepared_run,
        prepare=blocked,
        get_run=h.hydrate,
        utc_clock=lambda: h.now,
    )
    # timeout_at uses this original budget; preparation cannot invent a new one.
    with pytest.raises(TimeoutError):
        await h.coordinator.admit(
            first.ticket, first.record.envelope, deadline=asyncio.get_running_loop().time() + 0.02
        )
    assert started.is_set() and len(h.pool.rows) == 1 and not h.pool.runs
    assert h.pool.owner is None


async def test_absent_insert_conflict_rereads_winner_instead_of_returning_candidate() -> None:
    from maistro.runs.admission_identity import AdmissionRecordV2
    from maistro.tasks.admission_codec import encode_admission_record

    h = await make_harness()
    winner = AdmissionRecordV2(
        h.candidate(receipt_id="winner-receipt", request_id="winner-request"),
        uuid4(),
        int(h.now.timestamp() * 1_000_000) + 30_000_000,
    )

    def conflict(conn: _Connection, _row: dict[str, Any]) -> None:
        conn.rows[winner.envelope.scope_key] = dict(encode_admission_record(winner))
        h.pool.rows = deepcopy(conn.rows)

    h.pool.on_insert_conflict = conflict
    outcome = await h.coordinator.claim(h.candidate(), deadline=h.deadline())
    assert isinstance(outcome, Pending)
    assert outcome.record == winner
    assert h.prepared == 0 and not h.pool.runs
    assert sum("FOR UPDATE" in sql for _, sql, _ in h.pool.events) == 2


async def test_lock_wait_samples_fresh_time_before_lease_classification() -> None:
    h = await make_harness()
    first = await claim(h)
    h.pool.on_locked_read = lambda _conn: setattr(h, "now", h.now + timedelta(seconds=30))
    second = await claim(h)
    assert second.ticket.owner_token != first.ticket.owner_token
    assert second.record.envelope == first.record.envelope


async def test_owner_is_rechecked_after_read_only_preparation() -> None:
    h = await make_harness()
    first = await claim(h)
    successor_token = uuid4().hex
    h.before_prepare = lambda state: state.pool.rows[first.ticket.scope_key].update(
        claim_token=successor_token
    )
    result = await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert isinstance(result, StaleOwner)
    assert h.pool.rows[first.ticket.scope_key]["claim_token"] == successor_token
    assert h.prepared == 1 and not h.pool.runs


async def test_changed_full_envelope_cannot_pass_unchanged_receipt_and_owner_fences() -> None:
    h = await make_harness()
    first = await claim(h)
    changed = replace(first.record.envelope, project_id="different-project")
    result = await h.coordinator.admit(first.ticket, changed, deadline=h.deadline())
    assert isinstance(result, StaleOwner)
    assert not h.pool.runs and h.prepared == 0


async def test_unknown_rollback_with_expired_lease_returns_stale_without_release() -> None:
    h = await make_harness()
    first = await claim(h)
    h.pool.commit_faults = ["before"]
    h.pool.after_commit_fault = lambda _pool: setattr(h, "now", h.now + timedelta(seconds=30))
    result = await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert isinstance(result, StaleOwner)
    assert len(h.pool.rows) == 1 and not h.pool.runs
    assert not any(sql.startswith("DELETE") for _, sql, _ in h.pool.events)


@pytest.mark.parametrize(
    "field", ["request_id", "user_id", "service_principal_id", "delegation_id", "task_id"]
)
async def test_bound_replay_checks_original_provenance_not_only_scope(field: str) -> None:
    h = await make_harness()
    first = await claim(h)
    result = await admit(h, first)
    h.pool.runs[result.run_id]["payload"]["provenance"][field] = "foreign"
    with pytest.raises(RunIntegrityError):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert len(h.pool.runs) == 1 and h.prepared == 1


async def test_bound_replay_allows_new_runtime_provenance_and_terminal_status() -> None:
    h = await make_harness()
    first = await claim(h)
    original = await admit(h, first)
    payload = h.pool.runs[original.run_id]["payload"]
    payload["provenance"]["runtime_observation"] = "later"
    payload["status"] = "completed"
    payload["finished_at"] = h.now.isoformat()
    payload["result"] = {"files_changed": ["output.py"]}
    result = await admit(h, first)
    snapshot = Run.model_validate_json(result.run_snapshot.text)
    assert snapshot.status is RunStatus.COMPLETED
    assert snapshot.result == {"files_changed": ["output.py"]}
    assert result.run_id == original.run_id and not result.created
    assert h.prepared == 1


async def test_bounded_purge_drains_backlog_and_preserves_unknown_headers_and_submitted_scope() -> (
    None
):
    h = await make_harness()
    first = await claim(h)
    template = h.pool.rows[first.ticket.scope_key]
    for index in range(501):
        row = deepcopy(template)
        row["scope_key"] = f"{index:064x}"
        h.pool.rows[row["scope_key"]] = row
    unsupported = deepcopy(template)
    unsupported.update(scope_key="f" * 64, format_version=99)
    h.pool.rows[unsupported["scope_key"]] = unsupported
    malformed = deepcopy(template)
    malformed.update(scope_key="e" * 64, fingerprint="invalid-header")
    h.pool.rows[malformed["scope_key"]] = malformed
    h.now += timedelta(hours=24)
    h.coordinator._last_purge = -1
    renewed = await claim(h)
    assert renewed.ticket.generation_id != first.ticket.generation_id
    assert len(h.pool.rows) == 4  # submitted scope + one backlog row + two refused headers
    assert h.coordinator._purge_backlog
    await h.coordinator.claim(h.candidate(), deadline=h.deadline())
    assert len(h.pool.rows) == 3
    assert not h.coordinator._purge_backlog
    assert h.pool.rows[unsupported["scope_key"]] == unsupported
    assert h.pool.rows[malformed["scope_key"]] == malformed
    purge_queries = [sql for _, sql, _ in h.pool.events if "SKIP LOCKED" in sql]
    assert len(purge_queries) == 2
    assert all("LIMIT $2" in sql and "scope_key <> $3" in sql for sql in purge_queries)


async def test_purge_failure_rolls_back_and_does_not_replace_admission_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import maistro.tasks.pg_admission as module

    class Counter:
        value = 0

        def inc(self) -> None:
            self.value += 1

    counter = Counter()
    monkeypatch.setattr(module, "task_idempotency_purge_failures_total", counter)
    h = await make_harness()
    h.coordinator._last_purge = -1
    h.pool.purge_error = asyncpg.InterfaceError("purge connection failed")
    first = await claim(h)
    assert counter.value == 1
    assert len(h.pool.rows) == 1 and first.ticket.scope_key in h.pool.rows
    assert not h.pool.runs


async def test_unbound_legacy_key_stays_unresolved_without_fabricated_owner_or_run() -> None:
    from maistro.runs.admission_identity import LegacyUnresolved

    h = await make_harness()
    first = await claim(h)
    h.pool.rows[first.ticket.scope_key].update(format_version=1, receipt_id=None)
    original = deepcopy(h.pool.rows)
    outcome = await h.coordinator.claim(h.candidate(), deadline=h.deadline())
    assert isinstance(outcome, LegacyUnresolved)
    assert not hasattr(outcome.record, "owner_token")
    release = await h.coordinator.release(first.ticket, deadline=h.deadline())
    assert isinstance(release, LegacyUnresolved)
    assert h.pool.rows == original and not h.pool.runs and h.prepared == 0


async def test_completed_legacy_binding_uses_original_canonical_provenance() -> None:
    from maistro.runs.admission_identity import LegacyAdmissionRecord

    h = await make_harness()
    first = await claim(h)
    result = await admit(h, first)
    row = h.pool.rows[first.ticket.scope_key]
    row.update(format_version=1, receipt_id=None, request="{}")
    replayed = await h.coordinator.claim(h.candidate(request_id="retry"), deadline=h.deadline())
    assert isinstance(replayed, Replayed)
    assert isinstance(replayed.record, LegacyAdmissionRecord)
    replay = await h.coordinator.replay(
        replayed.record, origin_principal_id="origin", workspace_id="ws", deadline=h.deadline()
    )
    run = Run.model_validate_json(replay.run_snapshot.text)
    assert replay.run_id == result.run_id
    assert run.provenance["request_id"] == "request-original"
    assert run.provenance["service_principal_id"] == "service"
    assert h.prepared == 1


@pytest.mark.parametrize("principal,workspace", [("foreign", "ws"), ("origin", "foreign")])
async def test_replay_requires_authorized_origin_and_workspace(
    principal: str, workspace: str
) -> None:
    h = await make_harness()
    first = await claim(h)
    await admit(h, first)
    replayed = await h.coordinator.claim(h.candidate(), deadline=h.deadline())
    assert isinstance(replayed, Replayed)
    with pytest.raises(RunIntegrityError):
        await h.coordinator.replay(
            replayed.record,
            origin_principal_id=principal,
            workspace_id=workspace,
            deadline=h.deadline(),
        )
    assert h.hydrated == 1


async def test_preparation_refusal_after_owner_changes_does_not_release_successor() -> None:
    h = await make_harness()
    first = await claim(h)
    token = uuid4().hex
    h.before_prepare = lambda state: state.pool.rows[first.ticket.scope_key].update(
        claim_token=token
    )
    h.preparation_error = ValueError("read-only scope refusal")
    with pytest.raises(ValueError, match="read-only scope refusal"):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert h.pool.rows[first.ticket.scope_key]["claim_token"] == token
    assert not h.pool.runs


@pytest.mark.parametrize("deadline", [float("inf"), float("nan"), float("-inf")])
async def test_nonfinite_deadline_cannot_open_an_unbounded_operation(deadline: float) -> None:
    h = await make_harness()
    with pytest.raises(ValueError, match="finite"):
        await h.coordinator.claim(h.candidate(), deadline=deadline)
    assert h.pool.events == []


async def test_unavailable_archive_keeps_canonical_binding_without_replacement() -> None:
    h = await make_harness()
    first = await claim(h)
    result = await admit(h, first)
    h.pool.runs[result.run_id].update(payload=None, archive_key="archive-unavailable")
    with pytest.raises(ArchivedPayloadUnavailable):
        await h.coordinator.admit(first.ticket, first.record.envelope, deadline=h.deadline())
    assert len(h.pool.rows) == len(h.pool.runs) == 1 and h.prepared == 1
    assert h.pool.owner is None
