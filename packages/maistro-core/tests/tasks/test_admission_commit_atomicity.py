"""The admission-commit gap, closed: queue-level behavior on the atomic lane (#1845).

The failure class this issue pins (SQLite reproduction at 082dadb8/f5fa4377):
commit a Run, fail the completion, reopen, recover, expire the pending lease,
resubmit — and obtain two Run IDs. On the PostgreSQL tier the queue now routes
admission through :class:`PgRootAdmissionCoordinator`, which makes the Run
insert and the binding one commit, so the same class of experiment must yield
exactly one Run and one receipt. These tests run that experiment against the
queue itself, with the coordinator behind a recording stub whose decisions are
the ones the real coordinator's fences produce (the real one's decisions are
unit-pinned in ``test_pg_root_admission_coordinator.py``).

Also pinned here: the atomic path never awaits ``complete`` (the commit is the
event), the legacy path is untouched when no coordinator is wired, and the
late-owner rules — no release for a successor, retryability after a refusal.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from maistro.tasks.idempotency import (
    DERIVED_KEY_PREFIX,
    TASK_SUBMIT_ACTION,
    InMemoryTaskIdempotencyStore,
    admission_scope_key,
    request_fingerprint,
)
from maistro.tasks.models import TaskCreate
from maistro.tasks.pg_admission import (
    AdmissionBound,
    AdmissionRecord,
    AdmissionRowReplaced,
)
from maistro.tasks.queue import TaskQueue


def _request() -> TaskCreate:
    return TaskCreate(description="reconcile me", user_id="user-1")


def _scope_key() -> str:
    fingerprint = request_fingerprint(_request())
    return admission_scope_key(
        principal="user-1",
        workspace_id="ws",
        action=TASK_SUBMIT_ACTION,
        key=f"{DERIVED_KEY_PREFIX}{fingerprint}",
    )


class _BoundAdmitter:
    """The routed admitter's atomic half: prepare a Run, expose the
    coordinator. No database handles reach the queue through here."""

    def __init__(self, coordinator: _StubCoordinator) -> None:
        self._coordinator = coordinator
        self.workspace_id = "ws"
        self.prepared: list[Any] = []

    async def admitter_for(self, workspace_id: str | None = None) -> _BoundAdmitter:
        return self

    @property
    def coordinator(self) -> _StubCoordinator:
        return self._coordinator

    async def record_transition(self, run_id: str, status: Any) -> bool:
        # This seam stub has no Run store to rehydrate, so its replay cannot
        # claim dispatch ownership. The real task admitter performs that fence.
        return False

    async def prepare_run(self, task: Any) -> Any:
        self.prepared.append(task)
        return object()  # the Run's shape is the stores' concern, not the queue's


class _StubCoordinator:
    """``PgRootAdmissionCoordinator`` at the queue's seam: records every
    decision input and performs the joint commit by binding the claim-store
    row in the same step as the recorded insert."""

    def __init__(self, store: InMemoryTaskIdempotencyStore) -> None:
        self.store = store
        self.inserts: list[tuple[str, str]] = []  # (task_id, run_id)
        self.releases: list[AdmissionRecord] = []
        self.prepare_failures: list[Exception] = []

    async def bind_admission(  # type: ignore[no-untyped-def]
        self, *, scope_key, claim, task_id, prepare_run, **kw
    ) -> Any:
        if self.prepare_failures:
            raise self.prepare_failures.pop(0)
        run_id = f"run-{len(self.inserts) + 1}"
        # The joint commit: the insert and the binding are one fact.
        self.inserts.append((task_id, run_id))
        row = self.store._rows[scope_key]
        assert row is not None and row.task_id is None
        bound = replace(
            row,
            task_id=task_id,
            run_id=run_id,
            completed_at_us=row.created_at_us,
        )
        self.store._rows[scope_key] = bound
        return AdmissionBound(record=bound, task_id=task_id, run_id=run_id)

    async def release_claim(self, scope_key: str, claim: AdmissionRecord) -> bool:
        self.releases.append(claim)
        row = self.store._rows.get(scope_key)
        if row is None or row.task_id is not None:
            return False
        if (row.created_at_us, row.lease_expires_at_us) != (
            claim.created_at_us,
            claim.lease_expires_at_us,
        ):
            return False  # a successor owns this generation now
        del self.store._rows[scope_key]
        return True


def _queue(store: InMemoryTaskIdempotencyStore, coordinator: Any) -> TaskQueue:
    return TaskQueue(admitter=_BoundAdmitter(coordinator), idempotency_store=store)


async def _submit(queue: TaskQueue) -> Any:
    return await queue.submit(_request(), user_id="user-1", workspace_id="ws")


async def test_lost_completion_cannot_mint_a_second_run() -> None:
    """The issue's experiment, on the atomic lane: admit, 'die' before any
    acknowledgement matters, reopen, resubmit — one Run, one receipt."""
    store = InMemoryTaskIdempotencyStore()
    coordinator = _StubCoordinator(store)
    first = await _submit(_queue(store, coordinator))

    assert first.run_id == "run-1"
    # The binding is already durable, on the claim the joint commit wrote.
    row = await store.get(_scope_key())
    assert row is not None and row.admitted
    assert row.run_id == first.run_id

    # Process death: a fresh queue over the same durable store.
    replay = await _submit(_queue(store, _StubCoordinator(store)))

    assert replay.task_id == first.task_id
    assert replay.run_id == first.run_id
    assert len(coordinator.inserts) == 1  # exactly one canonical Run, ever


async def test_the_queue_never_calls_complete_on_the_atomic_lane() -> None:
    """Later acknowledgement is optional evidence, never the event that makes
    a committed Run replayable: the atomic path does not await it."""
    store = InMemoryTaskIdempotencyStore()
    coordinator = _StubCoordinator(store)
    calls: list[str] = []
    original = store.complete

    async def spy_complete(scope: str, **kw: Any) -> bool:
        calls.append(scope)
        return await original(scope, **kw)

    store.complete = spy_complete  # type: ignore[method-assign]
    task = await _submit(_queue(store, coordinator))

    assert task.run_id == "run-1"
    assert calls == []  # the joint commit replaced the acknowledgement


async def test_a_bound_generation_replays_regardless_of_lease_owner() -> None:
    store = InMemoryTaskIdempotencyStore()
    coordinator = _StubCoordinator(store)
    first = await _submit(_queue(store, coordinator))

    # Even a coordinator that would refuse everything cannot mint: the claim
    # flow itself answers the replay before any admission is attempted.
    untouched = _StubCoordinator(store)
    replay = await _submit(_queue(store, untouched))

    assert replay.task_id == first.task_id
    assert replay.run_id == first.run_id
    assert untouched.inserts == []


async def test_a_replaced_row_is_reacquired_without_releasing_the_successor() -> None:
    """Mid-admission takeover: the late owner re-claims (bounded) and never
    deletes the successor's claim; the outcome is still exactly one Run."""
    store = InMemoryTaskIdempotencyStore()
    coordinator = _StubCoordinator(store)
    real_bind = coordinator.bind_admission
    attempts: list[AdmissionRecord] = []

    async def replaced_once(**kw: Any) -> Any:  # type: ignore[no-untyped-def]
        claim: AdmissionRecord = kw["claim"]
        attempts.append(claim)
        if len(attempts) == 1:
            # A successor's fresh generation took the row over: re-stamped,
            # unbound, and not this caller's to insert into or release. The
            # coordinator's ``AdmissionRowReplaced`` carries the row its
            # locked recheck actually observed, so the stub re-stamps the
            # durable row with that successor's record too. Its lease is
            # already lapsed — the successor died mid-admission, the crash
            # class this issue closes — so the bounded re-claim below wins
            # the row back through the takeover fence rather than polling
            # out a live 30-second lease in wall-clock time, a wait CI's
            # --timeout=30 kills by construction.
            successor = replace(
                claim,
                claim_token=f"successor-{claim.claim_token}",
                task_id=None,
                run_id=None,
                completed_at_us=0,
                created_at_us=claim.created_at_us + 1_000_000,
                lease_expires_at_us=claim.created_at_us,
            )
            store._rows[kw["scope_key"]] = successor
            return AdmissionRowReplaced(record=successor)
        return await real_bind(**kw)

    coordinator.bind_admission = replaced_once  # type: ignore[method-assign]
    task = await _submit(_queue(store, coordinator))

    assert task.run_id == "run-1"
    assert len(attempts) == 2  # bounded re-claim happened
    assert coordinator.releases == []  # the successor's claim was never released
    assert len(coordinator.inserts) == 1


async def test_a_failed_preparation_releases_only_its_own_generation() -> None:
    """A refusal before the joint commit leaves the claim unbound and the
    retry fresh — and the fenced release is what the failure path uses."""
    store = InMemoryTaskIdempotencyStore()
    coordinator = _StubCoordinator(store)
    coordinator.prepare_failures.append(RuntimeError("scope refused"))

    queue = _queue(store, coordinator)
    with pytest.raises(RuntimeError):
        await _submit(queue)

    assert coordinator.inserts == []
    assert len(coordinator.releases) == 1
    assert await store.get(_scope_key()) is None

    # The retry mints fresh, with no residue of the failed attempt.
    task = await _submit(queue)
    assert task.run_id == "run-1"
    assert len(coordinator.inserts) == 1


async def test_the_legacy_path_survives_where_no_coordinator_is_wired() -> None:
    """Tiers without a coordinator keep claim -> admit -> best-effort
    complete, so a PG-only coordinator never changes their contract — here,
    the legacy release-on-failure is exactly what keeps the retry fresh."""
    store = InMemoryTaskIdempotencyStore()

    class _LegacyAdmitter:
        workspace_id = "ws"

        async def admitter_for(self, workspace_id: str | None = None) -> _LegacyAdmitter:
            return self

        @property
        def coordinator(self) -> None:
            return None

        async def admit(self, task: Any, *, workspace_id: str | None = None) -> str:
            raise RuntimeError("admission refused")

    queue = TaskQueue(admitter=_LegacyAdmitter(), idempotency_store=store)
    with pytest.raises(RuntimeError):
        await _submit(queue)
    assert await store.get(_scope_key()) is None  # released: the retry mints fresh
