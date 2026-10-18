"""Generation integration against migrated PostgreSQL and production JSON codecs.

PG17/18 CI requires these cases rather than silently skipping them. They cover
real SQL transactions, independent-connection contention and canonical stores;
they do not claim process-kill, dropped-COMMIT-response or physical-effect proof.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from maistro.observability.correlation import bind_execution_context
from maistro.persistence import _register_json_codecs
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs import admission_identity as identity
from maistro.runs.concurrency import RunConcurrencyExceeded, RunConcurrencyLimits
from maistro.runs.consumer_claim import ClaimingPgRunStore
from maistro.runs.evidence_json import decode_evidence, model_of_json
from maistro.runs.model import Run
from maistro.runs.wiring import _wire_admission_coordinator
from maistro.tasks.admission import (
    TaskRunAdmitter,
    build_root_admission_envelope,
    prepare_task_root,
)
from maistro.tasks.admission_codec import decode_admission_header, decode_admission_record
from maistro.tasks.idempotency import InMemoryTaskIdempotencyStore
from maistro.tasks.models import TaskCreate, TaskResponse
from maistro.tasks.pg_admission import (
    _INSERT_GENERATION_SQL,
    _LOCK_GENERATION_SQL,
    _V2_COLUMNS,
    PgRootAdmissionCoordinator,
)
from maistro.tasks.queue import TaskQueue
from maistro.testing.postgres import postgres_dsn


@pytest.fixture
async def single_pool(pg_pool: Any) -> AsyncIterator[Any]:
    # pg_pool establishes the genuinely migrated, per-test cleared database.
    if pg_pool is None:
        if os.getenv("MAISTRO_REQUIRE_PG_LEGS") == "1":
            pytest.fail("generation admission proof requires migrated PostgreSQL")
        pytest.skip("MAISTRO_TEST_PG_DSN is not set; no live durability proof")
    import asyncpg

    pool = await asyncpg.create_pool(
        postgres_dsn(), min_size=1, max_size=1, init=_register_json_codecs
    )
    try:
        yield pool
    finally:
        await pool.close()


async def _scope(pool: Any, *, limits: RunConcurrencyLimits | None = None) -> tuple[Any, Any, Any]:
    projects = PgProjectScopeStore(pool)
    root = await projects.create_root(f"generation-{uuid4().hex}")
    project = await projects.create(
        workspace_id=root.workspace_id, parent_project_id=root.project_id, name="Original scope"
    )
    runs = ClaimingPgRunStore(pool, project_store=projects, concurrency_limits=limits)
    return projects, project, runs


def _candidate(
    project: Any,
    *,
    now: datetime | None = None,
    description: str = "One root",
    key: str = "stable-key",
) -> identity.RootAdmissionEnvelope:
    return build_root_admission_envelope(
        TaskCreate(description=description),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        generation_id=uuid4(),
        receipt_id=TaskResponse.new_id(),
        created_at=now or datetime.now(UTC),
        origin_principal_id="origin",
        explicit_key=key,
        service_principal_id="original-service",
        delegation_id="original-delegation",
        actor_kind="service",
        request_id="original-request",
    )


def _coordinator(pool: Any, runs: Any, clock: Any = None) -> PgRootAdmissionCoordinator:
    kwargs = {"utc_clock": clock} if clock is not None else {}
    return PgRootAdmissionCoordinator(
        pool,
        insert_run=runs.insert_prepared_run,
        prepare=lambda envelope: prepare_task_root(
            envelope, prepare_root_run=runs.prepare_root_run
        ),
        get_run=runs.get_run,
        **kwargs,
    )


class _UnusedLegacyStore(InMemoryTaskIdempotencyStore):
    async def claim(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the generation queue must never fall back to old claims")


def _queue(projects: Any, project: Any, runs: Any, coordinator: Any) -> TaskQueue:
    assert coordinator.generation_admission_ready
    return TaskQueue(
        admitter=TaskRunAdmitter(
            runs,
            workspace_id=project.workspace_id,
            project_id=project.project_id,
            project_store=projects,
            coordinator=coordinator,
        ),
        idempotency_store=_UnusedLegacyStore(),
    )


@pytest.fixture
async def make_queue(
    single_pool: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Callable[[Any, Any, Any, Any], TaskQueue]]:
    """Own real receipt persistence as well as each queue until its loop closes."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from maistro.config.database import to_async_url

    # TaskQueue also persists TaskRecords through SQLAlchemy. Its production
    # cached engine would otherwise outlive these function-scoped event loops;
    # closing single_pool alone does not own those separate connections/writes.
    engine = create_async_engine(to_async_url(postgres_dsn()), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("maistro.tasks.queue.get_async_session_factory", lambda: factory)
    queues: list[TaskQueue] = []

    def make(projects: Any, project: Any, runs: Any, coordinator: Any) -> TaskQueue:
        queue = _queue(projects, project, runs, coordinator)
        queues.append(queue)
        return queue

    try:
        yield make
    finally:
        try:
            abandoned = await asyncio.gather(
                *(queue.drain_persistence(timeout=10) for queue in queues)
            )
            assert not any(abandoned), "live receipt writes must settle before loop teardown"
        finally:
            await engine.dispose()


async def _count(pool: Any, workspace: str) -> int:
    async with pool.acquire() as connection:
        return int(
            await connection.fetchval(
                "SELECT count(*) FROM canonical_runs WHERE workspace_id = $1", workspace
            )
        )


async def _read_record(pool: Any, scope_key: str) -> identity.AdmissionRecordV2:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT * FROM task_idempotency WHERE scope_key = $1", scope_key
        )
    assert row is not None
    record = decode_admission_record(row, header=decode_admission_header(row))
    assert isinstance(record, identity.AdmissionRecordV2)
    return record


async def test_composed_queue_replays_original_receipt_project_and_evidence(
    single_pool: Any, make_queue: Callable[[Any, Any, Any, Any], TaskQueue]
) -> None:
    projects, original, runs = await _scope(single_pool)
    coordinator = _wire_admission_coordinator(single_pool, runs)
    request = TaskCreate(
        description="Freeze original evidence", program_context={"value": math.nan}
    )
    with bind_execution_context(request_id="first-request"):
        first = await make_queue(projects, original, runs, coordinator).submit(
            request,
            user_id="origin",
            workspace_id=original.workspace_id,
            service_principal_id="first-service",
            delegation_id="first-delegation",
            actor_kind="service",
        )
    moved = await projects.create(
        workspace_id=original.workspace_id,
        parent_project_id=original.parent_project_id,
        name="Newly resolved project",
    )
    with bind_execution_context(request_id="retry-request"):
        replay = await make_queue(projects, moved, runs, coordinator).submit(
            request,
            user_id="origin",
            workspace_id=original.workspace_id,
            service_principal_id="retry-service",
            delegation_id="retry-delegation",
            actor_kind="service",
        )
    assert (replay.task_id, replay.run_id, replay.created_at) == (
        first.task_id,
        first.run_id,
        first.created_at,
    )
    assert replay.service_principal_id == "first-service"
    assert replay.delegation_id == "first-delegation"
    assert replay.program_context is not None and math.isnan(replay.program_context["value"])
    run = await runs.get_run(first.run_id)
    assert run.project_id == original.project_id and run.actor_principal_id == "origin"
    assert run.provenance["request_id"] == "first-request"
    assert math.isnan(run.provenance["task_payload"]["program_context"]["value"])
    assert await _count(single_pool, original.workspace_id) == 1
    async with single_pool.acquire() as connection:
        assert (
            await connection.fetchval(
                "SELECT jsonb_typeof(payload) FROM canonical_runs WHERE run_id = $1", first.run_id
            )
            == "object"
        )


async def test_concurrent_submitters_share_one_run_on_poolsize_one(
    single_pool: Any, make_queue: Callable[[Any, Any, Any, Any], TaskQueue]
) -> None:
    projects, project, runs = await _scope(single_pool)
    queue = make_queue(projects, project, runs, _coordinator(single_pool, runs))
    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        submissions = [
            group.create_task(
                queue.submit(
                    TaskCreate(description="One concurrent root"),
                    user_id="origin",
                    workspace_id=project.workspace_id,
                )
            )
            for _ in range(12)
        ]
    receipts = [submission.result() for submission in submissions]
    assert len({(receipt.task_id, receipt.run_id) for receipt in receipts}) == 1
    assert await _count(single_pool, project.workspace_id) == 1
    assert queue._pending.qsize() == 1


class _AbsentRowRace:
    """Coordinate reads only; every SQL statement and transaction stays real."""

    def __init__(self) -> None:
        self.both_absent = asyncio.Event()
        self.reads: list[tuple[int, int, str | None]] = []
        self.inserts: list[tuple[int, int, dict[str, Any], str | None]] = []


class _RacingConnection:
    def __init__(self, connection: Any, race: _AbsentRowRace) -> None:
        self.connection = connection
        self.race = race

    def __getattr__(self, name: str) -> Any:
        # In particular transaction() is asyncpg's actual transaction context.
        return getattr(self.connection, name)

    async def fetchrow(self, query: str, *args: Any, **kwargs: Any) -> Any:
        row = await self.connection.fetchrow(query, *args, **kwargs)
        if query == _LOCK_GENERATION_SQL:
            assert self.connection.is_in_transaction()
            self.race.reads.append(
                (
                    self.connection.get_server_pid(),
                    await self.connection.fetchval("SELECT txid_current()"),
                    None if row is None else row["generation_id"],
                )
            )
            if row is None:
                absent_reads = [read for read in self.race.reads if read[2] is None]
                assert len(absent_reads) <= 2
                if len(absent_reads) == 2:
                    self.race.both_absent.set()
                # Neither INSERT can start until both independent transactions
                # observed absence. No timing sleeps or simulated locks.
                await self.race.both_absent.wait()
        return row

    async def fetchval(self, query: str, *args: Any, **kwargs: Any) -> Any:
        if query != _INSERT_GENERATION_SQL:
            return await self.connection.fetchval(query, *args, **kwargs)
        assert self.race.both_absent.is_set()
        assert self.connection.is_in_transaction()
        result = await self.connection.fetchval(query, *args, **kwargs)
        self.race.inserts.append(
            (
                self.connection.get_server_pid(),
                await self.connection.fetchval("SELECT txid_current()"),
                dict(zip(_V2_COLUMNS, args, strict=True)),
                result,
            )
        )
        return result


class _RacingPool:
    def __init__(self, pool: Any, race: _AbsentRowRace) -> None:
        self.pool = pool
        self.race = race

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_RacingConnection]:
        async with self.pool.acquire() as connection:
            yield _RacingConnection(connection, self.race)


async def test_two_queues_race_absent_row_insert_and_reconcile_one_generation(
    single_pool: Any, make_queue: Callable[[Any, Any, Any, Any], TaskQueue]
) -> None:
    import asyncpg

    projects, project, runs = await _scope(single_pool)
    # Different pools/backends, unlike the pool-size-one serialization case.
    other_pool = await asyncpg.create_pool(
        postgres_dsn(), min_size=1, max_size=1, init=_register_json_codecs
    )
    try:
        other_projects = PgProjectScopeStore(other_pool)
        other_runs = ClaimingPgRunStore(other_pool, project_store=other_projects)
        race = _AbsentRowRace()
        queues = [
            make_queue(projects, project, runs, _coordinator(_RacingPool(single_pool, race), runs)),
            make_queue(
                other_projects,
                project,
                other_runs,
                _coordinator(_RacingPool(other_pool, race), other_runs),
            ),
        ]

        async def submit(replica: int) -> TaskResponse:
            with bind_execution_context(request_id=f"replica-{replica}-request"):
                return await queues[replica].submit(
                    TaskCreate(description="One cross-replica root"),
                    user_id="origin",
                    workspace_id=project.workspace_id,
                    idempotency_key="absent-row-race",
                    service_principal_id=f"replica-{replica}-service",
                    actor_kind="service",
                )

        async with asyncio.timeout(10), asyncio.TaskGroup() as group:
            submissions = [group.create_task(submit(replica)) for replica in range(2)]
        receipts = [submission.result() for submission in submissions]
        absent_reads = [read for read in race.reads if read[2] is None]
        assert len(absent_reads) == len(race.inserts) == 2
        assert len({pid for pid, _txid, _generation in absent_reads}) == 2
        assert len({txid for _pid, txid, _generation in absent_reads}) == 2
        assert {(pid, txid) for pid, txid, _generation in absent_reads} == {
            (pid, txid) for pid, txid, _row, _result in race.inserts
        }
        assert len({row["generation_id"] for _pid, _txid, row, _result in race.inserts}) == 2
        assert len({row["receipt_id"] for _pid, _txid, row, _result in race.inserts}) == 2
        winners = [entry for entry in race.inserts if entry[3] is not None]
        losers = [entry for entry in race.inserts if entry[3] is None]
        assert len(winners) == len(losers) == 1
        _winner_pid, _winner_txid, original_row, scope_key = winners[0]
        loser_pid, loser_txid, losing_row, _result = losers[0]
        assert scope_key == original_row["scope_key"] == losing_row["scope_key"]
        # A later queue poll cannot satisfy this same-transaction locking read.
        assert (loser_pid, loser_txid, original_row["generation_id"]) in race.reads
        original = decode_admission_record(
            original_row, header=decode_admission_header(original_row)
        )
        assert isinstance(original, identity.AdmissionRecordV2)
        assert scope_key is not None
        persisted = await _read_record(single_pool, scope_key)
        assert persisted.envelope == original.envelope and persisted.binding is not None
        assert {(receipt.task_id, receipt.run_id) for receipt in receipts} == {
            (original.envelope.receipt_id, persisted.binding.run_id)
        }
        run = await runs.get_run(persisted.binding.run_id)
        assert run.project_id == project.project_id
        assert run.provenance == decode_evidence(
            json.loads(original.envelope.provenance_snapshot.text)
        )
        original_receipt = model_of_json(TaskResponse, original.envelope.receipt_snapshot.text)
        assert {receipt.service_principal_id for receipt in receipts} == {
            original_receipt.service_principal_id
        }
        assert await _count(single_pool, project.workspace_id) == 1
        assert all(queue._pending.qsize() == 1 for queue in queues)
    finally:
        await other_pool.close()


async def test_takeover_rotates_owner_without_moving_generation(single_pool: Any) -> None:
    _projects, project, runs = await _scope(single_pool)
    clock = [datetime.now(UTC)]
    coordinator = _coordinator(single_pool, runs, lambda: clock[0])
    deadline = asyncio.get_running_loop().time() + 10
    original = _candidate(project, now=clock[0])
    first = await coordinator.claim(original, deadline=deadline)
    assert isinstance(first, identity.Claimed)
    clock[0] += timedelta(seconds=31)
    second = await coordinator.claim(_candidate(project, now=clock[0]), deadline=deadline)
    assert isinstance(second, identity.Claimed)
    assert second.record.envelope == original
    assert second.ticket.owner_token != first.ticket.owner_token
    assert isinstance(
        await coordinator.release(first.ticket, deadline=deadline), identity.StaleOwner
    )
    assert isinstance(
        await coordinator.admit(first.ticket, original, deadline=deadline), identity.StaleOwner
    )
    result = await coordinator.admit(second.ticket, original, deadline=deadline)
    assert isinstance(result, identity.RootAdmissionResult)
    run = model_of_json(Run, result.run_snapshot.text)
    assert run.provenance["request_id"] == "original-request"
    assert result.receipt_id == original.receipt_id
    assert await _count(single_pool, project.workspace_id) == 1
    binding = identity.AdmissionBinding(result.run_id, result.receipt_id)
    assert isinstance(
        await coordinator.complete(first.ticket, binding, deadline=deadline), identity.StaleOwner
    )
    assert isinstance(
        await coordinator.complete(second.ticket, binding, deadline=deadline), identity.Acknowledged
    )
    assert isinstance(
        await coordinator.release(second.ticket, deadline=deadline), identity.AlreadyBound
    )
    assert (await _read_record(single_pool, original.scope_key)).envelope == original


async def test_capacity_rollback_releases_only_its_unbound_claim(single_pool: Any) -> None:
    _projects, project, runs = await _scope(
        single_pool, limits=RunConcurrencyLimits(per_principal=0, per_workspace=0)
    )
    coordinator = _coordinator(single_pool, runs)
    deadline = asyncio.get_running_loop().time() + 10
    candidate = _candidate(project)
    claimed = await coordinator.claim(candidate, deadline=deadline)
    unrelated = await coordinator.claim(_candidate(project, key="unrelated"), deadline=deadline)
    assert isinstance(claimed, identity.Claimed) and isinstance(unrelated, identity.Claimed)
    with pytest.raises(RunConcurrencyExceeded):
        await coordinator.admit(claimed.ticket, candidate, deadline=deadline)
    assert await _count(single_pool, project.workspace_id) == 0
    async with single_pool.acquire() as connection:
        assert (
            await connection.fetchrow(
                "SELECT * FROM task_idempotency WHERE scope_key = $1", candidate.scope_key
            )
            is None
        )
    assert await _read_record(single_pool, unrelated.ticket.scope_key) == unrelated.record
    stale = identity.AdmissionTicket(
        unrelated.ticket.scope_key, unrelated.ticket.generation_id, uuid4()
    )
    assert isinstance(await coordinator.release(stale, deadline=deadline), identity.StaleOwner)
    assert await _read_record(single_pool, unrelated.ticket.scope_key) == unrelated.record
    assert isinstance(
        await coordinator.release(unrelated.ticket, deadline=deadline), identity.Released
    )


async def test_bound_replay_bypasses_capacity_and_optional_ack(single_pool: Any) -> None:
    _projects, project, runs = await _scope(
        single_pool, limits=RunConcurrencyLimits(per_principal=1, per_workspace=1)
    )
    coordinator = _coordinator(single_pool, runs)
    deadline = asyncio.get_running_loop().time() + 10
    candidate = _candidate(project)
    claimed = await coordinator.claim(candidate, deadline=deadline)
    assert isinstance(claimed, identity.Claimed)
    first = await coordinator.admit(claimed.ticket, candidate, deadline=deadline)
    assert isinstance(first, identity.RootAdmissionResult)
    # Never acknowledge: the durable binding alone must replay at a full ceiling.
    assert (await _read_record(single_pool, candidate.scope_key)).acknowledged_at_us is None
    fresh_coordinator = _coordinator(single_pool, runs)
    outcome = await fresh_coordinator.claim(_candidate(project), deadline=deadline)
    assert isinstance(outcome, identity.Replayed)
    replay = await fresh_coordinator.replay(
        outcome.record,
        origin_principal_id="origin",
        workspace_id=project.workspace_id,
        deadline=deadline,
    )
    assert (replay.run_id, replay.receipt_id) == (first.run_id, first.receipt_id)
    assert await _count(single_pool, project.workspace_id) == 1


async def test_insert_then_failure_rolls_back_run_and_preserves_unbound_identity(
    single_pool: Any,
) -> None:
    _projects, project, runs = await _scope(single_pool)

    async def fail_after_insert(conn: Any, run: Run) -> None:
        await runs.insert_prepared_run(conn, run)
        raise RuntimeError("injected after canonical INSERT, before binding")

    coordinator = PgRootAdmissionCoordinator(
        single_pool,
        insert_run=fail_after_insert,
        prepare=lambda envelope: prepare_task_root(
            envelope, prepare_root_run=runs.prepare_root_run
        ),
        get_run=runs.get_run,
    )
    deadline = asyncio.get_running_loop().time() + 10
    candidate = _candidate(project)
    claimed = await coordinator.claim(candidate, deadline=deadline)
    assert isinstance(claimed, identity.Claimed)
    with pytest.raises(RuntimeError, match="after canonical INSERT"):
        await coordinator.admit(claimed.ticket, candidate, deadline=deadline)
    assert await _count(single_pool, project.workspace_id) == 0
    persisted = await _read_record(single_pool, candidate.scope_key)
    assert persisted == claimed.record and persisted.binding is None


async def test_expiry_is_inclusive_before_payload_mismatch_or_snapshot_decode(
    single_pool: Any,
) -> None:
    _projects, project, runs = await _scope(single_pool)
    clock = [datetime.now(UTC)]
    coordinator = _coordinator(single_pool, runs, lambda: clock[0])
    deadline = asyncio.get_running_loop().time() + 10
    original = _candidate(project, now=clock[0])
    await coordinator.claim(original, deadline=deadline)
    async with single_pool.acquire() as connection:
        await connection.execute(
            "UPDATE task_idempotency SET request = 'invalid-json' WHERE scope_key = $1",
            original.scope_key,
        )
    clock[0] += timedelta(hours=24)
    fresh = _candidate(project, now=clock[0], description="Different allowed payload")
    result = await coordinator.claim(fresh, deadline=deadline)
    assert isinstance(result, identity.Claimed)
    assert result.record.envelope == fresh
    assert result.ticket.generation_id != original.generation_id
    assert (await _read_record(single_pool, fresh.scope_key)).envelope == fresh
