"""Task execution goes through the canonical Attempt seam (#143).

#41 gave every task a Run over a one-node Graph and then executed around it:
`list_node_runs()` returned nothing for every task the system had ever run, and
a retry was invisible. These tests hold the seam — one NodeRun per task, an
Attempt per physical try, evidence on the Attempt, and a receipt that still
reads exactly as it did before.
"""

from __future__ import annotations

import pytest

from maistro.agents.types import CodeOutput, ConductorOutput
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.execution import TASK_EXECUTOR_ID, TaskAttemptExecutor, TaskExecutionFailed
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner


def _ok(files: list[str] | None = None) -> ConductorOutput:
    return ConductorOutput(
        success=True,
        final_answer="done",
        code=CodeOutput(description="generated", files_changed=list(files or ["a.py"])),
    )


def _failed(answer: str = "the model refused") -> ConductorOutput:
    return ConductorOutput(success=False, final_answer=answer)


class _Executor:
    """Returns each queued output in turn, recording every call."""

    def __init__(self, *outputs: ConductorOutput) -> None:
        self._outputs = list(outputs) or [_ok()]
        self.calls: list[TaskCreate] = []

    async def __call__(self, request: TaskCreate) -> ConductorOutput:
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self._outputs) - 1)
        return self._outputs[index]


@pytest.fixture
async def wired():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    return queue, runs


def _runner(queue, runs, executor) -> TaskRunner:
    return TaskRunner(queue, executor=executor, attempts=TaskAttemptExecutor(runs))


# --- the criteria ---------------------------------------------------------


async def test_one_execution_produces_one_node_run_and_one_attempt(wired) -> None:
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))

    await _runner(queue, runs, _Executor())._execute_task(task.task_id)

    node_runs = await runs.list_node_runs(task.run_id or "")
    assert len(node_runs) == 1
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
    assert attempts[0].executor_id == TASK_EXECUTOR_ID


async def test_the_node_run_is_the_runs_own_graph_node(wired) -> None:
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))

    await _runner(queue, runs, _Executor())._execute_task(task.task_id)

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    graph_nodes = run.graph.materialize().nodes
    node_runs = await runs.list_node_runs(run.run_id)
    assert [nr.node_id for nr in node_runs] == [graph_nodes[0].node_id]


async def test_a_second_execution_adds_an_attempt_rather_than_a_node_run(wired) -> None:
    """Driven through the adapter, because the task machine has no retry.

    A receipt that reached COMPLETED or FAILED refuses PLANNING, so nothing
    re-enters `_execute_task` for the same task today. The seam still has to
    support a second physical try under the same logical node -- that is what
    makes a retry visible at all -- so this holds the adapter to it directly.
    The first try fails, which is the only state a real retry starts from: a
    completed NodeRun is terminal and cannot be tried again.
    """
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))
    await runs.transition_run(task.run_id or "", RunStatus.RUNNING)
    attempts_seam = TaskAttemptExecutor(runs)
    request = TaskCreate(description="Fix the parser")

    with pytest.raises(TaskExecutionFailed):
        await attempts_seam.execute(task.run_id or "", request, _Executor(_failed()))
    await attempts_seam.execute(task.run_id or "", request, _Executor(_ok(["b.py"])))

    node_runs = await runs.list_node_runs(task.run_id or "")
    assert len(node_runs) == 1
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [a.ordinal for a in attempts] == [1, 2]
    # The first Attempt keeps its own evidence: a retry adds a try, it does not
    # rewrite the record of the one before it.
    assert attempts[0].status is AttemptStatus.FAILED
    assert attempts[1].result["files_changed"] == ["b.py"]


async def test_the_attempt_carries_the_outcome_as_evidence(wired) -> None:
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))

    await _runner(queue, runs, _Executor(_ok(["x.py", "y.py"])))._execute_task(task.task_id)

    node_runs = await runs.list_node_runs(task.run_id or "")
    attempt = (await runs.list_attempts(node_runs[0].node_run_id))[0]
    assert attempt.result == {
        "success": True,
        "final_answer": "done",
        "files_changed": ["x.py", "y.py"],
    }
    assert attempt.started_at is not None
    assert attempt.finished_at is not None


async def test_a_failed_task_records_a_failed_attempt(wired) -> None:
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))

    await _runner(queue, runs, _Executor(_failed()))._execute_task(task.task_id)

    node_runs = await runs.list_node_runs(task.run_id or "")
    attempt = (await runs.list_attempts(node_runs[0].node_run_id))[0]
    assert attempt.status is AttemptStatus.FAILED
    assert "refused" in (attempt.error or "")


async def test_a_failed_task_still_terminalizes_its_receipt_and_run(wired) -> None:
    """The reconciler parks a Run whose only NodeRun failed. The receipt still
    has to be able to say the work is over -- WAITING has no edge to FAILED."""
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))

    await _runner(queue, runs, _Executor(_failed()))._execute_task(task.task_id)

    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.FAILED
    assert receipt.result is not None
    assert receipt.result.error == "the model refused"
    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status is RunStatus.FAILED


async def test_a_successful_task_reads_exactly_as_it_did_before(wired) -> None:
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))

    await _runner(queue, runs, _Executor(_ok(["z.py"])))._execute_task(task.task_id)

    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.COMPLETED
    assert receipt.result is not None
    assert receipt.result.files_changed == ["z.py"]
    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_a_cancelled_run_still_refuses_execution(wired) -> None:
    queue, runs = wired
    executor = _Executor()
    task = await queue.submit(TaskCreate(description="Fix the parser"))
    await runs.transition_run(task.run_id or "", RunStatus.CANCELLED)

    await _runner(queue, runs, executor)._execute_task(task.task_id)

    assert executor.calls == []
    assert await runs.list_node_runs(task.run_id or "") == []


# --- the unwired paths ----------------------------------------------------


async def test_without_the_seam_the_executor_still_runs() -> None:
    queue = TaskQueue()
    executor = _Executor()
    task = await queue.submit(TaskCreate(description="Fix the parser"))

    await TaskRunner(queue, executor=executor)._execute_task(task.task_id)

    assert len(executor.calls) == 1
    receipt = queue.get(task.task_id)
    assert receipt is not None
    assert receipt.status is TaskStatus.COMPLETED


async def test_a_task_with_no_run_is_executed_without_an_attempt(wired) -> None:
    """The queue admits without a Run when it has no admitter. A runner that
    does have the seam must still execute those, not refuse them."""
    _queue, runs = wired
    unadmitted = TaskQueue()
    executor = _Executor()
    task = await unadmitted.submit(TaskCreate(description="Fix the parser"))
    assert task.run_id is None

    await _runner(unadmitted, runs, executor)._execute_task(task.task_id)

    assert len(executor.calls) == 1


# --- the adapter itself ---------------------------------------------------


async def test_the_adapter_raises_the_output_it_could_not_complete(wired) -> None:
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))
    await runs.transition_run(task.run_id or "", RunStatus.RUNNING)

    with pytest.raises(TaskExecutionFailed) as excinfo:
        await TaskAttemptExecutor(runs).execute(
            task.run_id or "", TaskCreate(description="Fix the parser"), _Executor(_failed())
        )

    assert excinfo.value.output.final_answer == "the model refused"


async def test_the_adapter_returns_the_full_output_not_the_stored_summary(wired) -> None:
    """The Attempt keeps small evidence; the caller still needs the whole thing."""
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))
    await runs.transition_run(task.run_id or "", RunStatus.RUNNING)

    output = await TaskAttemptExecutor(runs).execute(
        task.run_id or "", TaskCreate(description="Fix the parser"), _Executor(_ok(["q.py"]))
    )

    assert isinstance(output, ConductorOutput)
    assert output.code is not None
    assert output.code.files_changed == ["q.py"]


# --- cancellation and shutdown --------------------------------------------


async def test_an_in_flight_attempt_is_cancellable_by_canonical_identity(wired) -> None:
    import asyncio

    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))
    await runs.transition_run(task.run_id or "", RunStatus.RUNNING)
    seam = TaskAttemptExecutor(runs)
    started = asyncio.Event()

    async def _slow(_request: TaskCreate) -> ConductorOutput:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("the cancelled Attempt must not finish its work")

    running = asyncio.create_task(
        seam.execute(task.run_id or "", TaskCreate(description="Fix the parser"), _slow)
    )
    await started.wait()

    assert await seam.cancel(task.run_id or "") is True
    with pytest.raises(asyncio.CancelledError):
        await running

    node_runs = await runs.list_node_runs(task.run_id or "")
    attempt = (await runs.list_attempts(node_runs[0].node_run_id))[0]
    assert attempt.status is AttemptStatus.CANCELLED


async def test_cancelling_a_task_with_nothing_in_flight_says_so(wired) -> None:
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))

    assert await TaskAttemptExecutor(runs).cancel(task.run_id or "") is False


async def test_shutdown_leaves_no_non_terminal_attempt(wired) -> None:
    """A worker cancelled mid-task must not leave a RUNNING Attempt behind.

    `AttemptExecutionService` terminalizes on `CancelledError` and reconciles
    before re-raising, which is what makes the record honest: the try that was
    interrupted says it was cancelled rather than staying forever running.
    """
    import asyncio

    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))
    started = asyncio.Event()

    async def _slow(_request: TaskCreate) -> ConductorOutput:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    runner = _runner(queue, runs, _slow)
    work = asyncio.create_task(runner._execute_task(task.task_id))
    await started.wait()
    work.cancel()
    await asyncio.gather(work, return_exceptions=True)

    node_runs = await runs.list_node_runs(task.run_id or "")
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [a.status for a in attempts] == [AttemptStatus.CANCELLED]
    node_run = await runs.get_node_run(node_runs[0].node_run_id)
    assert node_run is not None
    assert node_run.status is not RunStatus.RUNNING


# --- review findings ------------------------------------------------------


async def test_a_failed_attempt_keeps_the_work_it_did(wired) -> None:
    """A failed task can still have changed files; the Attempt must say so."""
    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))
    partial = ConductorOutput(
        success=False,
        final_answer="tests still red",
        code=CodeOutput(description="partial", files_changed=["half.py"]),
    )

    await _runner(queue, runs, _Executor(partial))._execute_task(task.task_id)

    node_runs = await runs.list_node_runs(task.run_id or "")
    attempt = (await runs.list_attempts(node_runs[0].node_run_id))[0]
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.error == "tests still red"
    assert attempt.result == {
        "success": False,
        "final_answer": "tests still red",
        "files_changed": ["half.py"],
    }


async def test_a_non_positive_timeout_is_refused_before_any_node_run(wired) -> None:
    _queue, runs = wired

    with pytest.raises(ValueError, match="timeout_s"):
        TaskAttemptExecutor(runs, timeout_s=0)
    with pytest.raises(ValueError, match="timeout_s"):
        TaskAttemptExecutor(runs, timeout_s=-1.0)


async def test_shutdown_waits_for_a_cancelled_attempt_to_terminalize(wired) -> None:
    """`stop()` used to cancel and return, so the CancelledError handler that
    terminalizes the Attempt could lose the race with the process exiting."""
    import asyncio

    queue, runs = wired
    task = await queue.submit(TaskCreate(description="Fix the parser"))
    started = asyncio.Event()
    settled = asyncio.Event()

    async def _slow(_request: TaskCreate) -> ConductorOutput:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            # Stand in for the terminalization work the real handler does.
            await asyncio.sleep(0)
            settled.set()
            raise
        raise AssertionError("unreachable")

    runner = _runner(queue, runs, _slow)
    await runner.start()
    # Generous: this only guards against a hang, and a thin bound here would
    # be its own wall-clock race under CI contention.
    await asyncio.wait_for(started.wait(), timeout=30)

    await runner.stop(drain_timeout=0.05)

    assert settled.is_set()
    node_runs = await runs.list_node_runs(task.run_id or "")
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [a.status for a in attempts] == [AttemptStatus.CANCELLED]
