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
from maistro.runs.cancellation import CancellationDisposition, CancellationReceipt
from maistro.runs.model import RunStatus
from maistro.tasks.admission import TaskRunAdmitter, WorkspaceRoutingAdmitter
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue


class _SilentReceiptAdmitter(TaskRunAdmitter):
    """An adapter whose receipt capability answers without evidence.

    The pre-#1242 shape is one gap (no ``cancel_run_receipt`` member at all);
    this is the shape between the eras — the member exists but contributes
    None, the same answer an unknown Run earns. The receipt must still be
    truthful: the fence is proven by the cancellation itself, the physical
    half stays uncertain.
    """

    async def cancel_run_receipt(self, run_id: str) -> CancellationReceipt | None:
        return None


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


async def _replica_over(runs: InMemoryRunStore, admitter: TaskRunAdmitter) -> TaskQueue:
    """A second replica over the same canonical store, holding no local receipts."""
    return TaskQueue(admitter=admitter)


async def _admitter_for_new_workspace(runs: InMemoryRunStore) -> TaskRunAdmitter:
    """A wired admitter for a replica whose Workspace differs from the owner's."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w-replica")
    return TaskRunAdmitter(runs, workspace_id="w-replica", project_id=root.project_id)


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


async def test_a_second_replica_settles_on_the_run_spine_s_own_evidence(wired) -> None:
    """A replica holding no receipt still cancels through the same authority.

    `get()` misses locally, so the answer comes from the shared tier: the
    canonical Run, then the admitter's receipt. The vocabulary, disposition
    and run_id must match what the owning replica itself would have reported
    — a task receipt that disagreed with its Run receipt is the #1242 defect
    in a second costume.
    """
    _queue_a, runs, task_id, run_id = await _submit(wired)
    replica = await _replica_over(runs, await _admitter_for_new_workspace(runs))

    answer = await replica.cancel_receipt(task_id)

    assert answer is not None
    assert answer.cancelled is True
    assert answer.stop_confirmed is True
    assert answer.disposition is CancellationDisposition.STOP_CONFIRMED
    assert answer.run_id == run_id
    # The cancelling replica derived everything from the shared tier and
    # fabricated no local projection of its own.
    assert replica.get(task_id) is None
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.CANCELLED


async def test_a_second_replica_refuses_a_run_that_already_settled(wired) -> None:
    """The shared tier says the work finished: a refusal, never a stop claim.

    A run that settled FAILED before the cancellation arrived is the same
    repeat-cancellation case the live path maps to 400; the shared path must
    answer with the same refusal receipt instead of terminalizing anything.
    """
    queue_a, runs, task_id, run_id = await _submit(wired)
    await runs.transition_run(run_id, RunStatus.RUNNING)
    assert await queue_a.update_status(task_id, TaskStatus.FAILED, error="boom") is True
    replica = await _replica_over(runs, await _admitter_for_new_workspace(runs))

    answer = await replica.cancel_receipt(task_id)

    assert answer is not None
    assert answer.cancelled is False
    assert answer.stop_confirmed is False
    assert answer.disposition is CancellationDisposition.COMPLETION_WON
    assert answer.run_id == run_id
    assert "refused" in answer.diagnosis


async def test_a_second_replica_whose_admitter_names_no_evidence_reports_uncertain(
    wired,
) -> None:
    """A silent receipt capability degrades to UNCERTAIN on the shared path.

    The fence the shared cancellation writes is durable and proven; nothing
    in the answer names the provider's fate, so the receipt must say exactly
    that rather than inherit a confirmed stop nobody observed.
    """
    _queue_a, runs, task_id, run_id = await _submit(wired)
    replica = await _replica_over(
        runs,
        _SilentReceiptAdmitter(
            runs,
            workspace_id="w-replica",
            project_store=InMemoryProjectScopeStore(),
        ),
    )

    answer = await replica.cancel_receipt(task_id)

    assert answer is not None
    assert answer.cancelled is True
    assert answer.stop_confirmed is False
    assert answer.disposition is CancellationDisposition.UNCERTAIN
    assert answer.run_id == run_id
    assert "no physical cancellation evidence" in answer.diagnosis


async def test_an_unevidenced_refusal_reports_the_actual_winner(wired) -> None:
    """A refusal with no receipt capability is COMPLETION_WON, not a stop.

    The pre-#1242 bool path collapsed a refusal into `cancelled: false` —
    correct by accident — and an acceptance into `cancelled: true`. Here the
    Run settles on its own terms before the cancellation arrives, the legacy
    adapter refuses, and the receipt must name the run's own outcome as the
    winner without claiming any stop happened.
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
    task = await queue.submit(TaskCreate(description="finished without me"))
    assert task.run_id is not None
    # The Run settles on its own terms; the local receipt stays live, because
    # nothing has reconciled it yet — exactly the drift the receipt path can
    # be called under.
    await runs.transition_run(task.run_id, RunStatus.RUNNING)
    await runs.transition_run(task.run_id, RunStatus.FAILED, error="boom")

    answer = await queue.cancel_receipt(task.task_id)

    assert answer is not None
    assert answer.cancelled is False
    assert answer.stop_confirmed is False
    assert answer.disposition is CancellationDisposition.COMPLETION_WON
    assert answer.run_id == task.run_id
    assert "refused" in answer.diagnosis


async def test_an_accepted_cancellation_with_no_run_identity_confirms_the_stop() -> None:
    """The receipt-only tier stops exactly what it held: nothing physical.

    A deployment with no admitter admits no Run, so an accepted cancellation
    there really did stop everything — the receipt says STOP_CONFIRMED with
    no run_id, the one shape where the bool path's confidence is earned.
    """
    queue = TaskQueue()  # no admitter: the documented receipt-only tier
    task = await queue.submit(TaskCreate(description="receipt only"))
    assert task.run_id is None

    answer = await queue.cancel_receipt(task.task_id)

    assert answer is not None
    assert answer.cancelled is True
    assert answer.stop_confirmed is True
    assert answer.disposition is CancellationDisposition.STOP_CONFIRMED
    assert answer.run_id is None
    assert "no canonical Run" in answer.diagnosis


async def test_receipt_evidence_needs_both_a_run_and_an_admitter() -> None:
    """The receipt probe contributes nothing when either input is missing.

    A run-less task has nothing the admitter could answer for, and an
    admitter-less queue has no canonical authority to ask. Both degrade to
    `None` — the caller's unevidenced fallback — never to a fabricated
    receipt.
    """
    queue = TaskQueue()  # no admitter

    assert await queue._run_cancel_receipt("task-1", None) is None
    assert await queue._run_cancel_receipt("task-1", "run-1") is None


async def test_an_admitter_answers_none_for_a_run_it_never_admitted(wired) -> None:
    """`cancel_run_receipt` on a foreign run_id is None, not a refusal."""
    queue, _runs = wired
    admitter = queue._admitter
    assert admitter is not None

    assert await admitter.cancel_run_receipt("no-such-run") is None


async def test_the_workspace_router_reports_receipts_through_its_bound_admitter() -> None:
    """`WorkspaceRoutingAdmitter.cancel_run_receipt` routes like `cancel_run`.

    The router binds one `TaskRunAdmitter` per Workspace; its receipt answer
    must come from that same bound authority over the shared canonical store,
    with `None` — not a refusal — for a run it never admitted.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    task = await queue.submit(TaskCreate(description="routed receipt"))
    assert task.run_id is not None
    router = WorkspaceRoutingAdmitter(runs, projects, default_workspace_id="w2")

    receipt = await router.cancel_run_receipt(task.run_id)

    assert receipt is not None
    assert receipt.run_id == task.run_id
    assert receipt.fenced is True
    assert receipt.disposition is CancellationDisposition.STOP_CONFIRMED
    # An unknown Run is not a refusal: the router has no receipt for it.
    assert await router.cancel_run_receipt("no-such-run") is None
