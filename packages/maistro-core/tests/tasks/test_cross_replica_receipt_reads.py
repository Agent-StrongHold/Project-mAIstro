"""#1690: a receipt is readable from any replica, backed by the shared tier.

The in-memory task store is per-process, so behind a round-robin load
balancer `GET /v1/tasks/{id}` used to 404 on every replica but the one that
accepted the `POST`. These tests stand up two `TaskQueue` "replicas" — two
bare queues over one shared canonical Run store and one shared durable
TaskRecord sink, no in-memory state in common — and pin the cross-replica
read contract on each edge that matters:

- a replica that never admitted the task answers `get_shared` with the same
  receipt identities the accepting replica returned (the durable Run is
  committed before the 202, so the answer exists even when the accepting
  replica's fire-and-forget TaskRecord write has not landed — the SIGKILL
  case);
- a foreign principal gains nothing through the durable lookup, from either
  durable source;
- terminal Run truth converges the projection — including a stale durable
  row that claims a success the Run never recorded, which must not be
  resurrected;
- a non-terminal Run caps the projection at non-terminal, so a half-written
  row cannot present finished work as done;
- cancellation works from a replica that holds no receipt, through the same
  canonical Run authority the owning replica's own cancel drives;
- a claim-lost dispatcher's dropped receipt routes its process's reads to
  the winner's Run truth instead of a stale non-terminal copy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import maistro.tasks.queue as queue_mod
from maistro.memory.store import TaskRecord
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TASK_PAYLOAD_KEY, TaskRunAdmitter
from maistro.tasks.models import TaskCreate, TaskResponse, TaskResult, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


class _FakeSession:
    """The durable TaskRecord sink both replicas "share" through one factory.

    Same shape as the receipt-durability suite's fake: `merge` upserts by
    primary key into one list, so both replicas read the same rows the way
    two processes read one PostgreSQL table.
    """

    def __init__(self, sink: list[TaskRecord]) -> None:
        self._sink = sink

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def merge(self, record: TaskRecord) -> TaskRecord:
        # `created_at` carries a server_default on the real table; emulate it
        # so rows read back through the shared path look like the database's.
        if record.created_at is None:
            record.created_at = datetime.now(UTC)
        for index, existing in enumerate(self._sink):
            if existing.id == record.id:
                self._sink[index] = record
                return record
        self._sink.append(record)
        return record

    async def commit(self) -> None:
        return None

    async def get(self, model: Any, key: Any) -> TaskRecord | None:
        for record in self._sink:
            if record.id == key:
                return record
        return None


def _install_shared_factory(monkeypatch: pytest.MonkeyPatch, sink: list[TaskRecord] | None) -> None:
    """Point the queue module at the shared sink (or at no database at all).

    The queue treats `get_async_session_factory()` as a sessionmaker: the
    result is called again per session (``async with factory() as session``).
    """
    if sink is None:
        monkeypatch.setattr(queue_mod, "get_async_session_factory", lambda: None)
        return

    def _sessionmaker() -> Any:
        return lambda: _FakeSession(sink)

    monkeypatch.setattr(queue_mod, "get_async_session_factory", _sessionmaker)


class _Replicas:
    """Two queues over one shared Run store: the two-replica composition."""

    def __init__(
        self,
        runs: InMemoryRunStore,
        admitter: TaskRunAdmitter,
        accepting: TaskQueue,
        peer: TaskQueue,
    ) -> None:
        self.runs = runs
        self.admitter = admitter
        self.accepting = accepting
        self.peer = peer


async def _two_replicas(
    monkeypatch: pytest.MonkeyPatch, *, shared_records: list[TaskRecord] | None = None
) -> _Replicas:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)
    _install_shared_factory(monkeypatch, shared_records)
    return _Replicas(
        runs=runs,
        admitter=admitter,
        # One process accepted the POST; the other only shares the durable
        # tier. Neither holds any of the other's memory.
        accepting=TaskQueue(admitter=admitter),
        peer=TaskQueue(admitter=admitter),
    )


async def _complete_run(runs: InMemoryRunStore, run_id: str, files: list[str]) -> None:
    """Drive a Run to COMPLETED the way the execution spine would."""
    run = await runs.get_run(run_id)
    assert run is not None
    if run.status is RunStatus.QUEUED:
        await runs.transition_run(run_id, RunStatus.RUNNING)
    await runs.transition_run(run_id, RunStatus.COMPLETED, result={"files_changed": files})


async def test_a_replica_that_never_admitted_the_task_still_answers_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replicas = await _two_replicas(monkeypatch)
    created = await replicas.accepting.submit(TaskCreate(description="visible everywhere"))

    # The peer holds no memory of this task, and the durable row may not have
    # landed (no shared record sink here — the fire-and-forget write is still
    # in flight as far as this composition is concerned). The Run, committed
    # before the accepting replica answered 202, is enough.
    receipt = await replicas.peer.get_shared(created.task_id)
    assert receipt is not None
    assert receipt.task_id == created.task_id
    assert receipt.run_id == created.run_id
    assert receipt.status is TaskStatus.QUEUED
    assert receipt.description == created.description
    assert receipt.user_id == DEFAULT_TEST_ACTOR_PRINCIPAL_ID

    # And the accepting replica's own answer is unchanged.
    local = await replicas.accepting.get_shared(created.task_id)
    assert local is not None and local.task_id == created.task_id


async def test_the_durable_row_serves_its_replica_even_before_the_run_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[TaskRecord] = []
    replicas = await _two_replicas(monkeypatch, shared_records=records)
    created = await replicas.accepting.submit(TaskCreate(description="row-backed"))
    # Let the accepting replica's scheduled fire-and-forget writes land, as
    # they would within moments on the real stack.
    for task in list(replicas.accepting._persist_writes):
        await task

    assert records, "the accepting replica must have written a durable row"
    receipt = await replicas.peer.get_shared(created.task_id)
    assert receipt is not None
    assert receipt.task_id == created.task_id
    assert receipt.run_id == created.run_id
    assert receipt.status is TaskStatus.QUEUED


async def test_a_foreign_principal_gains_nothing_through_the_durable_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[TaskRecord] = []
    replicas = await _two_replicas(monkeypatch, shared_records=records)
    created = await replicas.accepting.submit(TaskCreate(description="not yours"))
    for task in list(replicas.accepting._persist_writes):
        await task
    assert records, "the row-backed leg needs the durable row to exist"

    # Both durable sources refuse the foreign caller: the row names another
    # owner, and the Run's admission provenance does too.
    assert await replicas.peer.get_shared(created.task_id, user_id="mallory") is None
    assert await replicas.peer.get_shared(created.task_id + "zz", user_id="mallory") is None

    # The owner still reads it through the same shared path.
    owned = await replicas.peer.get_shared(created.task_id, user_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    assert owned is not None and owned.task_id == created.task_id


async def test_terminal_run_truth_converges_the_shared_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[TaskRecord] = []
    replicas = await _two_replicas(monkeypatch, shared_records=records)
    created = await replicas.accepting.submit(TaskCreate(description="converge on truth"))
    assert created.run_id is not None

    await _complete_run(replicas.runs, created.run_id, files=["src/one.py"])
    receipt = await replicas.peer.get_shared(created.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.COMPLETED
    assert receipt.result == TaskResult(files_changed=["src/one.py"])
    assert receipt.run_id == created.run_id


async def test_a_failed_run_never_resurrects_a_stale_durable_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[TaskRecord] = []
    replicas = await _two_replicas(monkeypatch, shared_records=records)
    created = await replicas.accepting.submit(TaskCreate(description="no fake success"))
    run_id = created.run_id or ""
    for task in list(replicas.accepting._persist_writes):
        await task

    # The durable row says COMPLETED — a write that landed before the Run
    # refused the outcome, or a stale receipt from a previous life of the row.
    stale = created.model_copy(
        update={
            "status": TaskStatus.COMPLETED,
            "phase": TaskStatus.COMPLETED.value,
            "result": TaskResult(files_changed=["ghost.py"]),
        }
    )
    records.clear()
    records.append(_record_for(stale))

    await replicas.runs.transition_run(run_id, RunStatus.RUNNING)
    await replicas.runs.transition_run(run_id, RunStatus.FAILED, error="the work failed")

    receipt = await replicas.peer.get_shared(created.task_id)
    assert receipt is not None
    # The Run is the execution truth: the row's success claim is not
    # resurrected over it.
    assert receipt.status is TaskStatus.FAILED
    assert receipt.result == TaskResult(error="the work failed")
    assert receipt.run_id == run_id


async def test_a_non_terminal_run_caps_the_shared_read_at_not_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[TaskRecord] = []
    replicas = await _two_replicas(monkeypatch, shared_records=records)

    # A durable row claiming a terminal outcome over a Run that is still
    # executing is stale in the dangerous direction. The accepting replica's
    # own row is drained first and REPLACED in place — appending a duplicate
    # would leave the landed row first in the sink and the read would never
    # see the stale claim.
    running = await replicas.accepting.submit(TaskCreate(description="still running"))
    for task in list(replicas.accepting._persist_writes):
        await task
    stale = running.model_copy(
        update={
            "status": TaskStatus.COMPLETED,
            "phase": TaskStatus.COMPLETED.value,
            "result": TaskResult(files_changed=["premature.py"]),
            "completed_at": datetime.now(UTC),
        }
    )
    _replace_row(records, stale)

    await replicas.runs.transition_run(running.run_id or "", RunStatus.RUNNING)
    receipt = await replicas.peer.get_shared(running.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.PLANNING
    assert receipt.result is None
    assert receipt.completed_at is None
    assert receipt.run_id == running.run_id

    # A Run still queued keeps even a terminal-claiming row at queued — a
    # dispatch that has not begun cannot be read as finished work.
    queued = await replicas.accepting.submit(TaskCreate(description="never dispatched"))
    for task in list(replicas.accepting._persist_writes):
        await task
    _replace_row(
        records,
        queued.model_copy(update={"status": TaskStatus.FAILED, "phase": TaskStatus.FAILED.value}),
    )
    queued_read = await replicas.peer.get_shared(queued.task_id)
    assert queued_read is not None
    assert queued_read.status is TaskStatus.QUEUED
    assert queued_read.result is None


async def test_cancellation_from_a_replica_without_the_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replicas = await _two_replicas(monkeypatch)
    created = await replicas.accepting.submit(TaskCreate(description="cancel me remotely"))

    outcome = await replicas.peer.cancel_shared(
        created.task_id, user_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    assert outcome is True
    run = await replicas.runs.get_run(created.run_id or "")
    assert run is not None and run.status is RunStatus.CANCELLED

    # The replica with no live copy reads the cancellation straight from the
    # durable tier.
    remote = await replicas.peer.get_shared(created.task_id)
    assert remote is not None and remote.status is TaskStatus.CANCELLED

    # The accepting replica's live receipt is its own phase carrier and stays
    # as it was until its worker next touches the task — at which point the
    # Run's refusal reconciles the projection (#849): the exact convergence
    # path the owning replica's runner drives on its next dispatch attempt.
    assert replicas.accepting.get(created.task_id) is not None
    refused = await replicas.accepting.update_status(created.task_id, TaskStatus.PLANNING)
    assert refused is False
    converged = replicas.accepting.get(created.task_id)
    assert converged is not None and converged.status is TaskStatus.CANCELLED

    # Repeating the cancellation is refused, not an error — the same contract
    # as the local repeat-cancel path (the route maps False to 400).
    assert (
        await replicas.peer.cancel_shared(created.task_id, user_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
        is False
    )

    # A task neither process nor the durable tier knows is None (the 404), and
    # a foreign principal cannot even learn that it exists.
    assert await replicas.peer.cancel_shared("no-such-task") is None
    assert await replicas.peer.cancel_shared(created.task_id, user_id="mallory") is None


async def test_a_claim_lost_dispatcher_reads_the_winner_after_abandoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loser of the canonical claim stops answering from stale memory."""
    replicas = await _two_replicas(monkeypatch)
    created = await replicas.accepting.submit(TaskCreate(description="one winner only"))
    run_id = created.run_id or ""

    # The losing process still holds the receipt it dequeued before the
    # winner's claim landed: put the copy in its memory the way its own
    # dispatch left it.
    replicas.peer._tasks[created.task_id] = created.model_copy(deep=True)
    assert replicas.peer.get(created.task_id) is not None

    # The winner claims the Run; the loser's copy is now stale.
    await replicas.runs.transition_run(run_id, RunStatus.RUNNING)

    assert replicas.peer.abandon_local_receipt(created.task_id) is True
    assert replicas.peer.get(created.task_id) is None

    # Reads now project the winner's Run — in-flight while it runs, terminal
    # once it completes — instead of the stale QUEUED copy.
    in_flight = await replicas.peer.get_shared(created.task_id)
    assert in_flight is not None and in_flight.status is TaskStatus.PLANNING
    await _complete_run(replicas.runs, run_id, files=["winner.py"])
    settled = await replicas.peer.get_shared(created.task_id)
    assert settled is not None and settled.status is TaskStatus.COMPLETED
    assert settled.result == TaskResult(files_changed=["winner.py"])

    # Abandoning again finds nothing to drop.
    assert replicas.peer.abandon_local_receipt(created.task_id) is False


async def test_a_shared_read_without_any_durable_source_is_a_plain_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replicas = await _two_replicas(monkeypatch, shared_records=None)
    assert await replicas.peer.get_shared("absent-task") is None


async def test_a_malformed_run_payload_answers_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replicas = await _two_replicas(monkeypatch)
    created = await replicas.accepting.submit(TaskCreate(description="corrupted"))
    stored = replicas.runs._runs[created.run_id or ""]  # type: ignore[attr-defined]
    stored.provenance[TASK_PAYLOAD_KEY] = {"not": "a task"}

    assert await replicas.peer.get_shared(created.task_id) is None


async def test_an_admitter_store_outage_degrades_to_the_durable_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[TaskRecord] = []
    replicas = await _two_replicas(monkeypatch, shared_records=records)
    created = await replicas.accepting.submit(TaskCreate(description="db down"))
    for task in list(replicas.accepting._persist_writes):
        await task

    class _FailingFinder:
        def __getattr__(self, name: str) -> Any:
            raise AttributeError(name)

        async def lookup_run(self, run_id: str) -> None:
            return None

        async def find_task_run(self, task_id: str) -> TaskResponse | None:
            raise RuntimeError("synthetic store outage")

        async def admit(self, task: TaskResponse, *, workspace_id: str | None = None) -> str:
            raise RuntimeError("unused")

    failing = TaskQueue(admitter=_FailingFinder())  # type: ignore[arg-type]
    receipt = await failing.get_shared(created.task_id)
    assert receipt is not None
    assert receipt.task_id == created.task_id
    # Without a Run to reconcile against, the durable row's own reading is
    # served verbatim — no fabrication in either direction.
    assert receipt.status is TaskStatus.QUEUED


async def test_a_queue_without_an_admitter_or_without_the_finder_still_serves_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared read predates neither seam: absence contributes nothing."""
    records: list[TaskRecord] = []
    replicas = await _two_replicas(monkeypatch, shared_records=records)
    created = await replicas.accepting.submit(TaskCreate(description="no finder here"))
    for task in list(replicas.accepting._persist_writes):
        await task
    assert records, "the row-backed leg needs the durable row to exist"

    # No admitter at all: the Run lookup is skipped, the row answers.
    bare = TaskQueue()
    receipt = await bare.get_shared(created.task_id)
    assert receipt is not None and receipt.task_id == created.task_id
    assert receipt.status is TaskStatus.QUEUED

    # An admitter from before `find_task_run` existed (a custom
    # implementation, say): the missing finder contributes nothing rather
    # than failing the read.
    class _PreFinderAdmitter:
        async def lookup_run(self, run_id: str) -> None:
            return None

    old = TaskQueue(admitter=_PreFinderAdmitter())  # type: ignore[arg-type]
    receipt = await old.get_shared(created.task_id)
    assert receipt is not None and receipt.task_id == created.task_id


def test_owner_evidence_falls_back_to_the_task_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pure owner rule: provenance user_id, else the payload's, else none."""
    from maistro.tasks.queue import _receipt_owner_of_run

    def _run_stub(provenance: dict[str, Any]) -> Any:
        class _Run:
            pass

        run = _Run()
        run.provenance = provenance
        return run

    # The admission provenance names the owner outright.
    assert _receipt_owner_of_run(_run_stub({"user_id": "alice"})) == "alice"
    # No top-level claim: the immutable task payload carries it.
    assert (
        _receipt_owner_of_run(_run_stub({TASK_PAYLOAD_KEY: {"user_id": "bob", "description": "x"}}))
        == "bob"
    )
    # A non-string top-level claim is not an owner; the payload still is.
    assert (
        _receipt_owner_of_run(_run_stub({"user_id": 7, TASK_PAYLOAD_KEY: {"user_id": "carol"}}))
        == "carol"
    )
    # A payload that is not a dict contributes nothing either.
    assert _receipt_owner_of_run(_run_stub({TASK_PAYLOAD_KEY: "garbage"})) == ""


async def test_an_ownerless_run_is_visible_only_to_empty_scoping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No principal claim anywhere: a named caller learns nothing (#1690)."""
    replicas = await _two_replicas(monkeypatch)
    created = await replicas.accepting.submit(TaskCreate(description="nobody's"))
    stored = replicas.runs._runs[created.run_id or ""]  # type: ignore[attr-defined]
    del stored.provenance["user_id"]
    # The payload stays a valid receipt snapshot; it simply names nobody.
    payload = created.model_dump(mode="json")
    payload.pop("user_id", None)
    stored.provenance[TASK_PAYLOAD_KEY] = payload

    # A principal who names themselves is refused — an empty owner matches
    # only a caller who scopes by empty, never one who names a principal.
    assert await replicas.peer.get_shared(created.task_id, user_id="mallory") is None
    unscoped = await replicas.peer.get_shared(created.task_id)
    assert unscoped is not None and unscoped.task_id == created.task_id


async def test_cancel_shared_cancels_a_locally_held_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The local half of `cancel_shared` is `cancel`, unchanged."""
    replicas = await _two_replicas(monkeypatch)
    created = await replicas.accepting.submit(TaskCreate(description="cancel me locally"))

    outcome = await replicas.accepting.cancel_shared(
        created.task_id, user_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    assert outcome is True
    run = await replicas.runs.get_run(created.run_id or "")
    assert run is not None and run.status is RunStatus.CANCELLED


async def test_a_durable_receipt_with_no_run_behind_it_is_not_cancellable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No execution identity, no canonical authority to cancel through."""
    records: list[TaskRecord] = []
    replicas = await _two_replicas(monkeypatch, shared_records=records)
    created = await replicas.accepting.submit(TaskCreate(description="unanchored"))
    for task in list(replicas.accepting._persist_writes):
        await task

    # A row whose run_id is absent: the queue does not fabricate an anchor.
    # The Run lookup must contribute nothing for the row to be the whole
    # story — here the admitter predates the finder, as a custom
    # implementation might.
    class _PreFinderAdmitter:
        async def lookup_run(self, run_id: str) -> None:
            return None

        async def cancel_run(self, run_id: str) -> bool:
            raise AssertionError("no anchor means cancel_run is never reached")

    anchorless = created.model_copy(update={"run_id": None})
    _replace_row(records, anchorless)
    finderless = TaskQueue(admitter=_PreFinderAdmitter())  # type: ignore[arg-type]
    assert await finderless.cancel_shared(created.task_id) is False

    # Nor does a queue with no admitter cancel through a row that has one.
    _replace_row(records, created)
    bare = TaskQueue()
    assert await bare.cancel_shared(created.task_id) is False


def _record_for(task: TaskResponse) -> TaskRecord:
    """The durable row one receipt writes, via the queue's own snapshot."""
    from maistro.tasks.queue import _record_values

    return TaskRecord(**_record_values(task))


def _row_index(records: list[TaskRecord], task_id: str) -> int:
    """The sink position of one task's row (TaskRecord equality is identity)."""
    return next(i for i, record in enumerate(records) if record.id == task_id)


def _replace_row(records: list[TaskRecord], task: TaskResponse) -> None:
    """Overwrite one task's row in place, preserving its server timestamp.

    The fake session stamps `created_at` (a server default) only on `merge`,
    so a row built outside it carries None where the database would never
    allow it — and `_task_from_record` refuses that row outright.
    """
    old = records[_row_index(records, task.task_id)]
    fresh = _record_for(task)
    fresh.created_at = old.created_at
    records[_row_index(records, task.task_id)] = fresh


def _unpublished(task_id: str, description: str) -> TaskResponse:
    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.QUEUED,
        description=description,
        workspace="w1",
        user_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        tier=2,
        created_at=datetime.now(UTC),
    )


def test_projection_pins_the_run_identity_over_a_disagreeing_row() -> None:
    """A shared read never lets a row rename the execution identity."""
    from maistro.tasks.queue import _project_run_onto_receipt

    receipt = _unpublished("task-1", "disagreeing row")
    receipt.run_id = "run-from-row"
    run = _run_stub("run-canonical", RunStatus.COMPLETED)
    projected = _project_run_onto_receipt(receipt, run)
    assert projected.run_id == "run-canonical"
    assert projected.status is TaskStatus.COMPLETED


def _run_stub(run_id: str, status: RunStatus) -> Any:
    """A minimal canonical Run double for the pure projection helper."""

    class _Run:
        pass

    run = _Run()
    run.run_id = run_id
    run.status = status
    run.started_at = None
    run.finished_at = None
    run.result = {"files_changed": ["a.py"]}
    run.error = None
    return run


async def test_find_run_by_task_id_scopes_to_the_task_queue_source() -> None:
    """The provenance read is the queue's own; a foreign source never answers."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id)
    created = await TaskQueue(admitter=admitter).submit(
        TaskCreate(description="findable", user_id="user-a")
    )

    found = await runs.find_run_by_task_id(created.task_id)
    assert found is not None and found.run_id == created.run_id
    # Source-unscoped reads find it too; a foreign source filter does not.
    assert await runs.find_run_by_task_id(created.task_id, admission_source=None) is not None
    assert await runs.find_run_by_task_id(created.task_id, admission_source="chat") is None
    assert await runs.find_run_by_task_id("no-such-task") is None
    # The admitted Run's provenance names both the receipt id and the source.
    run = await runs.get_run(created.run_id or "")
    assert run is not None
    assert run.provenance["task_id"] == created.task_id
