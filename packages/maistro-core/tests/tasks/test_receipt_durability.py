"""#849: task failure/completion receipts are durable, legal, and drain-safe.

The queue's receipt used to be the least honest record in the system: a
dispatch failure before PLANNING could not transition QUEUED -> FAILED (the
receipt sat QUEUED forever, its gauge leaked, pruning never saw it), the
fire-and-forget TaskRecord writes were abandoned whenever the event loop
closed before they landed, and a forced shutdown could leave a COMPLETED Run
with no receipt at all. These tests pin the repair on all four edges: the
legal failure transition, the drain owned by the runner's shutdown, recovery
reconciling terminal receipts from the canonical Run, and idempotence of that
reconciliation — plus the cancel-race semantics the reconciliation introduces
(a mid-call reconcile is a win; a repeat cancel of a terminal receipt is not).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import maistro.tasks.queue as queue_mod
from maistro.agents.types import CodeOutput, ConductorOutput
from maistro.observability.metrics import active_tasks
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.lanes import LaneGate
from maistro.tasks.models import TaskCreate, TaskResponse, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner

_TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


def _gauge_total(gauge: Any) -> float:
    """The gauge's whole (label-less) reading, across whatever samples exist."""
    return sum(float(sample["value"]) for sample in gauge.collect())


class _FakeSession:
    def __init__(self, sink: list[Any], *, fail: bool = False, delay: float = 0.0) -> None:
        self._sink = sink
        self._fail = fail
        self._delay = delay

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def merge(self, record: Any) -> Any:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("synthetic database outage")
        # `created_at` carries a server_default on the real table; emulate it so
        # rows read back through `get` look like the database's.
        if getattr(record, "created_at", None) is None:
            from datetime import UTC, datetime

            record.created_at = datetime.now(UTC)
        self._sink.append(record)
        return record

    async def commit(self) -> None:
        return None

    async def get(self, model: Any, key: Any) -> Any:
        for record in self._sink:
            if record.id == key:
                return record
        return None


def _install_factory(
    monkeypatch: pytest.MonkeyPatch, *, fail: bool = False, delay: float = 0.0
) -> list[Any]:
    sink: list[Any] = []
    monkeypatch.setattr(
        queue_mod,
        "get_async_session_factory",
        lambda: lambda: _FakeSession(sink, fail=fail, delay=delay),
    )
    return sink


def _live_gate(runner: TaskRunner) -> None:
    """The gate `start()` would build, for driving one dispatch by hand."""
    runner._gate = LaneGate(
        runner._max_workers,
        live_reserved=runner._live_slots,
        background_reserved=runner._background_slots,
    )


async def success_executor(_request: TaskCreate) -> ConductorOutput:
    return ConductorOutput(
        success=True,
        code=CodeOutput(files_changed=["a.py"], description="changed a file"),
        final_answer="done",
    )


@pytest.fixture
async def wired():
    """An admitter-backed queue over an in-memory canonical store."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    return queue, runs


# ── the legal failure transition ──────────────────────────────────


async def test_a_pre_planning_failure_is_a_legal_transition_and_leaks_no_gauge() -> None:
    """QUEUED -> FAILED used to be refused, so a dispatch that failed before
    any phase ran stranded the receipt QUEUED forever: the gauge never
    decremented and terminal pruning never saw it."""
    queue = TaskQueue()
    baseline = _gauge_total(active_tasks)

    task = await queue.submit(TaskCreate(description="never reaches planning"))
    assert _gauge_total(active_tasks) == pytest.approx(baseline + 1)

    assert await queue.update_status(task.task_id, TaskStatus.FAILED, error="claim lost") is True

    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.FAILED
    assert receipt.completed_at is not None
    assert _gauge_total(active_tasks) == pytest.approx(baseline), (
        "the failed receipt must release its gauge"
    )
    assert receipt.status in _TERMINAL, "terminal pruning must be able to see it"


async def test_queued_still_cannot_jump_to_completed() -> None:
    """Making failure legal from QUEUED does not relax the rest of the machine:
    a task-driven QUEUED -> COMPLETED remains illegal — a receipt reaches
    COMPLETED only by executing, or by reconciling to a Run that did."""
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="one"))

    assert await queue.update_status(task.task_id, TaskStatus.COMPLETED) is False
    assert queue.get(task.task_id).status is TaskStatus.QUEUED


class _PlanningExplodes(TaskQueue):
    """A queue whose PLANNING write itself fails — the pre-PLANNING failure."""

    def __init__(self) -> None:
        super().__init__()
        self.boom_task: str | None = None

    async def update_status(self, task_id: str, status: TaskStatus, **kwargs: Any) -> bool:
        if status is TaskStatus.PLANNING and task_id == self.boom_task:
            raise RuntimeError("queue write exploded before planning")
        return await super().update_status(task_id, status, **kwargs)


async def test_an_exception_before_planning_fails_the_receipt_not_strands_it() -> None:
    """A worker exception between dequeue and the first phase write used to
    call `update_status(FAILED)` and be refused by the machine, leaving the
    receipt QUEUED behind dead work. Now the failure lands."""
    queue = _PlanningExplodes()
    baseline = _gauge_total(active_tasks)
    task = await queue.submit(TaskCreate(description="exploding dispatch"))
    queue.boom_task = task.task_id

    runner = TaskRunner(queue, success_executor)
    _live_gate(runner)
    # `_admit_and_run` is the runner's whole dispatch body — acquire, execute,
    # release — so the lane permit stays balanced while the queue's own
    # PLANNING write fails inside the claim.
    await runner._admit_and_run(task.task_id, task.lane, task.priority_tier)

    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.FAILED
    assert receipt.result is not None and "exploded before planning" in receipt.result.error
    assert _gauge_total(active_tasks) == pytest.approx(baseline)


async def test_claim_body_failure_before_planning_lands_the_failure() -> None:
    """The claim context manager is the first failure point inside a dispatch:
    its own failure branch (`update_status(FAILED)` from QUEUED) must be a
    legal transition now, not a refused write that strands the receipt."""
    queue = _PlanningExplodes()
    baseline = _gauge_total(active_tasks)
    task = await queue.submit(TaskCreate(description="exploding claim body"))
    queue.boom_task = task.task_id

    with pytest.raises(RuntimeError, match="exploded before planning"):
        async with queue.claim(task.task_id):
            await queue.update_status(task.task_id, TaskStatus.PLANNING)

    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.FAILED
    assert receipt.result is not None and "exploded before planning" in receipt.result.error
    assert _gauge_total(active_tasks) == pytest.approx(baseline)


async def test_a_refusal_with_a_live_run_is_deferred_not_failed(wired) -> None:
    """The defer branch of the reconcile: the Run refuses but is alive and
    non-terminal (QUEUED — e.g. this dispatcher lost the claim race and the
    winner owns the work). Failing the receipt would lie; it stays QUEUED,
    still mirroring its dispatchable Run, and recovery re-drives both."""
    queue, _runs = wired
    task = await queue.submit(TaskCreate(description="owned elsewhere"))
    # Refuse every transition while the Run stays QUEUED and readable.
    queue._admitter.record_transition = lambda *args, **kwargs: asyncio.sleep(0, result=False)  # type: ignore[method-assign, assignment]

    assert await queue.update_status(task.task_id, TaskStatus.PLANNING) is False

    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.QUEUED, (
        "a live canonical owner owns the outcome; the receipt mirrors it"
    )


async def test_a_missing_run_gets_an_explicit_canonical_error_receipt() -> None:
    """A receipt whose Run does not exist cannot be reconciled from it; the
    honest disposition is an explicit canonical error receipt, not a QUEUED
    row nobody will ever advance."""

    class _GhostRunAdmitter:
        """Admits a run_id that never resolves and refuses everything."""

        async def admit(self, task: Any, *, workspace_id: str | None = None) -> str:
            return "run-that-will-not-resolve"

        async def record_transition(self, run_id: str, status: TaskStatus, **kwargs: Any) -> bool:
            return False

        async def cancel_run(self, run_id: str) -> bool:
            return False

        async def lookup_run(self, run_id: str) -> None:
            return None

    baseline = _gauge_total(active_tasks)
    queue = TaskQueue(admitter=_GhostRunAdmitter())  # type: ignore[arg-type]
    task = await queue.submit(TaskCreate(description="orphaned identity"))

    assert await queue.update_status(task.task_id, TaskStatus.PLANNING) is False

    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.FAILED
    assert receipt.result is not None
    assert "canonical error receipt" in receipt.result.error
    assert _gauge_total(active_tasks) == pytest.approx(baseline)


async def test_a_cancellation_that_won_the_race_is_true_a_repeat_is_false(wired) -> None:
    """Two truths the cancel API must hold at once (#849): a receipt the
    canonical cancellation reconciled to CANCELLED *during* the call is a
    successful cancellation (True, not a 400), while a request that found the
    receipt already terminal is a repeat of an old cancellation (False, the
    route's pinned 400)."""
    queue, _runs = wired
    task = await queue.submit(TaskCreate(description="race the reconcile"))
    assert task.run_id

    async def _cancel_and_reconcile(run_id: str) -> bool:
        # The worker-side reconcile winning the race: the receipt flips to
        # CANCELLED while `cancel()` sits between its two reads.
        await queue.update_status(task.task_id, TaskStatus.CANCELLED)
        return True

    admitter = queue._admitter
    assert admitter is not None
    admitter.cancel_run = _cancel_and_reconcile  # type: ignore[method-assign]

    assert await queue.cancel(task.task_id) is True
    # And the pinned repeat contract: an already-terminal receipt stays False.
    assert await queue.cancel(task.task_id) is False


# ── the shutdown drain ────────────────────────────────────────────


async def test_drain_persistence_waits_for_in_flight_writes(monkeypatch) -> None:
    """A scheduled write is not a landed write. The drain is what turns the
    fire-and-forget model into one a graceful shutdown can own."""
    sink = _install_factory(monkeypatch, delay=0.2)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="slow write"))
    assert sink == [], "the write is scheduled, not landed"

    assert await queue.drain_persistence() == 0

    assert len(sink) == 1
    assert sink[0].id == task.task_id
    # Idempotent: nothing left to wait for.
    assert await queue.drain_persistence() == 0


async def test_drain_persistence_cancels_writes_that_never_settle(monkeypatch) -> None:
    """A write that would hold shutdown open forever is cancelled and counted,
    not abandoned to the event loop's death."""
    started: asyncio.Event = asyncio.Event()
    release: asyncio.Event = asyncio.Event()

    class _HeldSession(_FakeSession):
        async def merge(self, record: Any) -> Any:
            started.set()
            await release.wait()
            return await super().merge(record)

    sink: list[Any] = []
    monkeypatch.setattr(queue_mod, "get_async_session_factory", lambda: lambda: _HeldSession(sink))
    queue = TaskQueue()
    await queue.submit(TaskCreate(description="held write"))
    await started.wait()

    assert await queue.drain_persistence(timeout=0.05) == 1

    assert sink == []
    assert not queue._persist_writes, "cancelled writes must not linger mid-flight"


async def test_stop_immediately_after_completion_drains_the_terminal_write(
    wired, monkeypatch
) -> None:
    """Process stop right after a completion: the runner's shutdown owns the
    receipt write that records how the work ended."""
    queue, _runs = wired
    sink = _install_factory(monkeypatch, delay=0.2)
    runner = TaskRunner(queue, success_executor)
    await runner.start()
    task = await queue.submit(TaskCreate(description="finish then die"))
    while queue.get(task.task_id).status is not TaskStatus.COMPLETED:  # type: ignore[union-attr]
        await asyncio.sleep(0.01)
    assert sink == [], "the terminal write is still in flight"

    await runner.stop(drain_timeout=5.0)

    terminal = [record for record in sink if record.id == task.task_id]
    assert terminal, "shutdown must land the completion it scheduled"
    assert terminal[-1].status == TaskStatus.COMPLETED.value
    assert terminal[-1].result is not None


async def test_drain_from_the_runner_signal_path(monkeypatch) -> None:
    """`drain()` — the signal-handler path — carries the same ownership."""
    sink = _install_factory(monkeypatch, delay=0.1)
    queue = TaskQueue()
    runner = TaskRunner(queue, success_executor)
    await runner.start()
    task = await queue.submit(TaskCreate(description="signal me"))
    while queue.get(task.task_id).status is not TaskStatus.COMPLETED:  # type: ignore[union-attr]
        await asyncio.sleep(0.01)

    await runner.drain(timeout=5.0)

    assert any(record.id == task.task_id for record in sink)


# ── recovery reconciles terminal receipts from the canonical owner ──


async def _completed_task_run(queue: TaskQueue) -> TaskResponse:
    """Drive one admitted task to a canonical COMPLETED Run with a result."""
    task = await queue.submit(
        TaskCreate(description="finished while the process lived"), user_id="alice"
    )
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING) is True
    assert await queue.update_status(task.task_id, TaskStatus.CODING) is True
    assert (
        await queue.update_status(
            task.task_id, TaskStatus.COMPLETED, result={"files_changed": ["done.py"]}
        )
        is True
    )
    return task


async def _failed_task_run(queue: TaskQueue) -> TaskResponse:
    task = await queue.submit(TaskCreate(description="died mid-flight"), user_id="alice")
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING) is True
    assert await queue.update_status(task.task_id, TaskStatus.CODING) is True
    assert await queue.update_status(task.task_id, TaskStatus.FAILED, error="boom") is True
    return task


async def test_a_completed_run_is_not_permanently_missing_its_receipt(wired, monkeypatch) -> None:
    """The forced-shutdown window: the terminal transition committed on the
    Run, the in-flight receipt write never landed. Recovery writes the receipt
    from the canonical owner — status, result and identity included."""
    queue, runs = wired
    task = await _completed_task_run(queue)
    run = await runs.get_run(task.run_id or "")
    assert run is not None and run.status is RunStatus.COMPLETED

    # Restart: a fresh process, a fresh database session, no memory of the task.
    sink = _install_factory(monkeypatch)
    restarted = TaskQueue()
    assert await restarted.recover(runs) == 0

    rows = [record for record in sink if record.id == task.task_id]
    assert len(rows) == 1, "exactly one reconciled receipt row"
    assert rows[0].status == TaskStatus.COMPLETED.value
    assert rows[0].result is not None
    assert rows[0].result.get("files_changed") == ["done.py"]
    assert rows[0].run_id == task.run_id
    assert rows[0].user_id == "alice"


async def test_a_failed_run_recovers_its_error_receipt(wired, monkeypatch) -> None:
    queue, runs = wired
    task = await _failed_task_run(queue)

    sink = _install_factory(monkeypatch)
    restarted = TaskQueue()
    await restarted.recover(runs)

    (row,) = [record for record in sink if record.id == task.task_id]
    assert row.status == TaskStatus.FAILED.value
    assert row.result is not None and row.result.get("error") == "boom"


async def test_durable_write_failure_then_restart_still_recovers_the_receipt(
    wired, monkeypatch
) -> None:
    """Best-effort persistence may fail while serving (ADR-018); the restart
    reconciles from the Run, so the outage cost a delay, not the receipt."""
    queue, runs = wired
    task = await _completed_task_run(queue)

    _install_factory(monkeypatch, fail=True)
    failing = TaskQueue()
    # Recovery during the outage writes nothing and raises nothing.
    assert await failing.recover(runs) == 0

    sink = _install_factory(monkeypatch)
    recovered = TaskQueue()
    await recovered.recover(runs)
    (row,) = [record for record in sink if record.id == task.task_id]
    assert row.status == TaskStatus.COMPLETED.value


async def test_terminal_receipt_recovery_is_idempotent(wired, monkeypatch) -> None:
    """Repeated recovery neither duplicates rows nor rewrites a receipt that
    already tells the truth."""
    queue, runs = wired
    task = await _completed_task_run(queue)

    sink = _install_factory(monkeypatch)
    restarted = TaskQueue()
    await restarted.recover(runs)
    after_first = [record for record in sink if record.id == task.task_id]
    assert len(after_first) == 1

    # A second restart over the same durable facts: the terminal row is read,
    # found already true, and not rewritten.
    second = TaskQueue()
    await second.recover(runs)
    after_second = [record for record in sink if record.id == task.task_id]
    assert after_second == after_first

    # And a warm queue holding a live non-terminal copy has that copy pulled
    # to the Run's state, with the durable row found already true and left
    # untouched — no duplicate write, no duplicate result.
    before = len(sink)
    warm = TaskQueue()
    warm._tasks[task.task_id] = task.model_copy(
        update={
            "status": TaskStatus.QUEUED,
            "phase": "queued",
            "result": None,
            "started_at": None,
            "completed_at": None,
        }
    )
    await warm.recover(runs)
    assert len(sink) == before, "an already-true durable receipt is not rewritten"
    live = warm.get(task.task_id)
    assert live is not None and live.status is TaskStatus.COMPLETED
    assert live.result is not None and live.result.files_changed == ["done.py"]
