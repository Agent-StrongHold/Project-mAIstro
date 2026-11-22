"""A task cancellation receipt agrees with the Run receipt it came from (#1242).

`DELETE /tasks/{id}` used to render `cancelled: true` from the bare accept
bool, which every caller read as "the provider stopped". `TaskQueue.
cancel_receipt` keeps the accept/refuse trichotomy and adds the physical
evidence in the Run spine's own vocabulary, so a task receipt, a Run receipt
and a Conductor receipt cannot disagree about requested-vs-confirmed. These
regressions drive the real `TaskQueue` over an admitter-backed canonical
store and pin what each answer must say.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, InMemoryRunStore
from maistro.runs.cancellation import CancellationDisposition
from maistro.runs.model import RunStatus
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue


@pytest.fixture
async def wired():
    """An admitter-backed queue over an in-memory canonical Run store."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    return queue, runs


async def _submit(wired) -> tuple[TaskQueue, InMemoryRunStore, str, str]:
    """A submitted task and the canonical Run admitted behind it."""
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="receipt me"))
    assert task.run_id is not None
    return queue, runs, task.task_id, task.run_id


async def test_a_queued_cancellation_confirms_that_no_physical_try_existed(wired) -> None:
    """Cancel before dispatch: confirmed, because nothing physical ever existed.

    The proof is the fence — the durable CANCELLED is what refuses a competing
    consumer claim, so no invocation can start afterwards either.
    """
    queue, runs, task_id, run_id = await _submit(wired)

    answer = await queue.cancel_receipt(task_id)

    assert answer is not None
    assert answer.cancelled is True
    assert answer.stop_confirmed is True
    assert answer.disposition is CancellationDisposition.STOP_CONFIRMED
    assert answer.run_id == run_id
    assert "no physical" in answer.diagnosis
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.CANCELLED
    receipt = queue.get(task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.CANCELLED


async def test_an_in_flight_cancellation_under_a_remote_lease_is_not_a_stop(wired) -> None:
    """The Attempt is RUNNING under a lease this process cannot signal.

    The receipt must read `STOP_PENDING` — the fence is durable, the stop is
    not proven — name the lease holder that has to stop the try, and leave the
    durable Attempt row alone.
    """
    queue, runs, task_id, run_id = await _submit(wired)
    run = await runs.get_run(run_id)
    assert run is not None
    node_id = run.graph.materialize().nodes[0].node_id
    node_run = await runs.create_node_run(run_id, node_id=node_id)
    attempt = await runs.create_attempt(
        node_run.node_run_id,
        runtime_id="remote-runtime",
        lease_holder="worker-b",
        lease_ttl=timedelta(minutes=5),
    )
    assert attempt.execution_lease is not None
    await runs.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )

    answer = await queue.cancel_receipt(task_id)

    assert answer is not None
    assert answer.cancelled is True
    assert answer.stop_confirmed is False
    assert answer.disposition is CancellationDisposition.STOP_PENDING
    assert "worker-b" in answer.diagnosis
    persisted = await runs.get_attempt(attempt.attempt_id)
    assert persisted is not None
    assert persisted.status is AttemptStatus.RUNNING


async def test_a_terminal_receipt_refuses_and_claims_no_stop(wired) -> None:
    """A task that already settled on its own terms refuses cancellation.

    The route renders the 400 from `cancelled=False`; the receipt still names
    the actual winner so nothing anywhere claims a stop.
    """
    queue, runs, task_id, run_id = await _submit(wired)
    # A receipt terminalizes with its Run, and a Run fails only from RUNNING.
    await runs.transition_run(run_id, RunStatus.RUNNING)
    assert await queue.update_status(task_id, TaskStatus.FAILED, error="boom") is True

    answer = await queue.cancel_receipt(task_id)

    assert answer is not None
    assert answer.cancelled is False
    assert answer.stop_confirmed is False
    assert answer.disposition is CancellationDisposition.COMPLETION_WON
    assert answer.run_id == run_id
    assert "refused" in answer.diagnosis


async def test_an_admitter_without_the_receipt_capability_reports_uncertain(wired) -> None:
    """The `getattr` probe (#1338) must degrade to UNCERTAIN, not confidence.

    An adapter compiled against the pre-#1242 shape cancels fine; the queue
    simply has no physical evidence, so an accepted cancellation behind a Run
    says `uncertain` — the fence is proven, the stop is not.
    """

    class _PreReceiptAdmitter(TaskRunAdmitter):
        """An adapter that predates `cancel_run_receipt` (#1242)."""

        cancel_run_receipt = None  # type: ignore[assignment]

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(
        admitter=_PreReceiptAdmitter(runs, workspace_id="w1", project_id=root.project_id)
    )
    task = await queue.submit(TaskCreate(description="old adapter"))
    assert task.run_id is not None

    answer = await queue.cancel_receipt(task.task_id)

    assert answer is not None
    assert answer.cancelled is True
    assert answer.stop_confirmed is False
    assert answer.disposition is CancellationDisposition.UNCERTAIN
    assert "no physical cancellation evidence" in answer.diagnosis


async def test_an_unknown_task_is_not_a_receipt_at_all(wired) -> None:
    """`None` is the route's 404 — never a fabricated answer."""
    queue, _runs = wired

    assert await queue.cancel_receipt("no-such-task") is None


async def test_the_receipt_runs_on_the_run_spine_clock_not_the_wall_clock(wired) -> None:
    """The receipt's fence timestamp is the Run's, not a second now()."""
    queue, runs, task_id, run_id = await _submit(wired)

    before = datetime.now(UTC)
    answer = await queue.cancel_receipt(task_id)
    run = await runs.get_run(run_id)

    assert answer is not None and run is not None and run.finished_at is not None
    assert before <= run.finished_at <= datetime.now(UTC)
