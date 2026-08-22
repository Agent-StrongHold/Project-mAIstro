"""A task's Run now has a NodeRun and an Attempt (#143).

Before this, `list_node_runs` on a task's Run returned `[]` for every task the
deployment had ever run: #41 gave the work an execution identity and execution
went around it.

The sharp case here is the one the spine exists for: a conductor that ran to
completion and reports `success=False` is a *logical* failure whose *physical*
execution finished normally. The Attempt must say COMPLETED and the NodeRun must
say FAILED. Collapsing those would make an honest "I couldn't" indistinguishable
from a crashed process.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.agents.types import CodeOutput, ConductorOutput
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.execution import TASK_EXECUTOR_ID, TaskAttemptRunner, TaskWorkItem
from maistro.tasks.models import TaskCreate, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner

WORKSPACE = "task-workspace"


def _ok(files: list[str] | None = None) -> ConductorOutput:
    return ConductorOutput(
        success=True,
        final_answer="done",
        code=CodeOutput(files_changed=files or ["a.py"], description="done"),
    )


def _domain_failure() -> ConductorOutput:
    return ConductorOutput(success=False, final_answer="could not find the module")


@pytest.fixture
async def spine():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    store = InMemoryRunStore(project_store=projects)
    admitter = TaskRunAdmitter(store, workspace_id=WORKSPACE, project_id=root.project_id)
    return store, admitter


async def _admitted(spine: Any, **create_kwargs: Any):
    """A task submitted through the real queue, so its Run is admitted as it ships."""
    _store, admitter = spine
    queue = TaskQueue(admitter=admitter)
    task = await queue.submit(TaskCreate(description="ship it", task_type="code", **create_kwargs))
    return queue, task


# ── the physical record exists at all ─────────────────────────────


async def test_execution_creates_a_node_run_and_an_attempt(spine) -> None:
    store, _admitter = spine
    _queue, task = await _admitted(spine)
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_ok()))

    await attempts.execute(run_id=task.run_id, task_id=task.task_id, request=_request(task))

    node_runs = await store.list_node_runs(task.run_id)
    assert len(node_runs) == 1
    assert len(await store.list_attempts(node_runs[0].node_run_id)) == 1


async def test_the_attempt_names_the_task_runner(spine) -> None:
    """So a recovery scan can tell task work from graph traversal without
    reading the Run's provenance."""
    store, _admitter = spine
    _queue, task = await _admitted(spine)
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_ok()))

    await attempts.execute(run_id=task.run_id, task_id=task.task_id, request=_request(task))

    node_run = (await store.list_node_runs(task.run_id))[0]
    attempt = (await store.list_attempts(node_run.node_run_id))[0]
    assert attempt.executor_id == TASK_EXECUTOR_ID
    assert attempt.ordinal == 1


async def test_the_node_run_is_under_the_tasks_own_graph_node(spine) -> None:
    store, _admitter = spine
    _queue, task = await _admitted(spine)
    run = await store.get_run(task.run_id)
    assert run is not None
    expected = run.graph.materialize().nodes[0].node_id
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_ok()))

    await attempts.execute(run_id=task.run_id, task_id=task.task_id, request=_request(task))

    assert (await store.list_node_runs(task.run_id))[0].node_id == expected


# ── logical vs physical ───────────────────────────────────────────


async def test_success_completes_both_layers(spine) -> None:
    store, _admitter = spine
    _queue, task = await _admitted(spine)
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_ok(["x.py"])))

    result = await attempts.execute(
        run_id=task.run_id, task_id=task.task_id, request=_request(task)
    )

    assert result.success
    node_run = (await store.list_node_runs(task.run_id))[0]
    attempt = (await store.list_attempts(node_run.node_run_id))[0]
    assert attempt.status is AttemptStatus.COMPLETED
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.result == {"files_changed": ["x.py"]}


async def test_a_domain_failure_completes_the_attempt_and_fails_the_node_run(spine) -> None:
    """The case this module exists for. The conductor ran fine and could not do
    the work: physically completed, logically failed."""
    store, _admitter = spine
    _queue, task = await _admitted(spine)
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_domain_failure()))

    result = await attempts.execute(
        run_id=task.run_id, task_id=task.task_id, request=_request(task)
    )

    assert result.success is False
    node_run = (await store.list_node_runs(task.run_id))[0]
    attempt = (await store.list_attempts(node_run.node_run_id))[0]
    assert attempt.status is AttemptStatus.COMPLETED
    assert node_run.status is RunStatus.FAILED
    assert node_run.error == "could not find the module"


async def test_the_accepted_outcome_matches_its_persisted_attempt(spine) -> None:
    """The NodeRun's authoritative evidence has to be the Attempt that actually
    ran, not a reconstruction of it."""
    store, _admitter = spine
    _queue, task = await _admitted(spine)
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_ok()))

    await attempts.execute(run_id=task.run_id, task_id=task.task_id, request=_request(task))

    node_run = (await store.list_node_runs(task.run_id))[0]
    attempt = (await store.list_attempts(node_run.node_run_id))[0]
    assert node_run.accepted_outcome is not None
    assert node_run.accepted_outcome.attempt_result.attempt_id == attempt.attempt_id


async def test_a_raised_exception_fails_the_attempt_physically(spine) -> None:
    store, _admitter = spine
    _queue, task = await _admitted(spine)

    async def _boom(_request: Any) -> ConductorOutput:
        raise RuntimeError("provider exploded")

    attempts = TaskAttemptRunner(store, executor=_boom)

    with pytest.raises(RuntimeError):
        await attempts.execute(run_id=task.run_id, task_id=task.task_id, request=_request(task))

    node_run = (await store.list_node_runs(task.run_id))[0]
    attempt = (await store.list_attempts(node_run.node_run_id))[0]
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.error is not None
    assert "provider exploded" in attempt.error


async def test_a_raised_exception_leaves_nothing_parked(spine) -> None:
    """The reconciler parks a failed NodeRun and Run in WAITING for a domain
    with a retry policy to pick up. The task domain has none, so parked is a
    state nothing would ever move them out of — the Run would look live
    forever."""
    store, _admitter = spine
    _queue, task = await _admitted(spine)

    async def _boom(_request: Any) -> ConductorOutput:
        raise RuntimeError("boom")

    attempts = TaskAttemptRunner(store, executor=_boom)

    with pytest.raises(RuntimeError):
        await attempts.execute(run_id=task.run_id, task_id=task.task_id, request=_request(task))

    node_run = (await store.list_node_runs(task.run_id))[0]
    run = await store.get_run(task.run_id)
    assert node_run.status is RunStatus.FAILED
    assert run is not None
    # RUNNING, not FAILED: the caller reports the receipt failed next, and that
    # is the transition that carries the error message.
    assert run.status is RunStatus.RUNNING


# ── refusals and integrity ────────────────────────────────────────


async def test_a_run_that_does_not_resolve_is_refused(spine) -> None:
    store, _admitter = spine
    _queue, task = await _admitted(spine)
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_ok()))

    with pytest.raises(RunIntegrityError):
        await attempts.execute(run_id="no-such-run", task_id=task.task_id, request=_request(task))


async def test_a_multi_node_run_is_refused(spine) -> None:
    """Executing the first node of a Graph that has several, as if it were the
    only one, would silently run the wrong work."""
    from maistro.graph import Graph, Node

    store, _admitter = spine
    _queue, task = await _admitted(spine)
    admitted = await store.get_run(task.run_id)
    assert admitted is not None
    graph = Graph(
        workspace_id=WORKSPACE,
        project_id=admitted.project_id,
        name="two",
        nodes=[Node(node_type="agent", name="a"), Node(node_type="agent", name="b")],
    )
    run = await store.create_run(graph)
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_ok()))

    with pytest.raises(RunIntegrityError):
        await attempts.execute(run_id=run.run_id, task_id="t", request=TaskCreate(description="x"))


async def test_re_executing_a_task_creates_a_second_node_run(spine) -> None:
    """A task run twice is two logical tries under one Run, each with its own
    Attempt — not one Attempt rewritten. The NodeRun is terminal after the
    first, so the second try is a new NodeRun rather than a retry of the old."""
    store, _admitter = spine
    _queue, task = await _admitted(spine)
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_domain_failure()))
    await attempts.execute(run_id=task.run_id, task_id=task.task_id, request=_request(task))
    await attempts.execute(run_id=task.run_id, task_id=task.task_id, request=_request(task))

    node_runs = await store.list_node_runs(task.run_id)
    assert [node_run.ordinal for node_run in node_runs] == [1, 2]
    for node_run in node_runs:
        assert len(await store.list_attempts(node_run.node_run_id)) == 1


# ── the runner drives it, and stays as it was without a store ─────


async def test_the_runner_executes_through_the_attempt(spine) -> None:
    store, admitter = spine
    queue = TaskQueue(admitter=admitter)
    runner = TaskRunner(queue, executor=lambda _req: _completed(_ok()), run_store=store)
    task = await queue.submit(TaskCreate(description="ship it", task_type="code"))

    await runner._execute_task(task.task_id)

    assert len(await store.list_node_runs(task.run_id)) == 1


async def test_the_runner_without_a_store_is_exactly_as_it_was(spine) -> None:
    """Every test that builds a runner without a spine, and every process that
    has none, must keep working."""
    calls: list[Any] = []

    async def _executor(request: Any) -> ConductorOutput:
        calls.append(request)
        return _ok()

    queue = TaskQueue()
    runner = TaskRunner(queue, executor=_executor)
    task = await queue.submit(TaskCreate(description="ship it"))

    await runner._execute_task(task.task_id)

    assert len(calls) == 1


async def test_a_task_with_no_run_falls_back_to_the_executor(spine) -> None:
    """`TaskQueue` admits without a Run when it has no admitter. Inventing one
    here would take a decision that belongs to admission."""
    store, _admitter = spine
    calls: list[Any] = []

    async def _executor(request: Any) -> ConductorOutput:
        calls.append(request)
        return _ok()

    queue = TaskQueue()
    runner = TaskRunner(queue, executor=_executor, run_store=store)
    task = await queue.submit(TaskCreate(description="ship it"))
    assert task.run_id is None

    await runner._execute_task(task.task_id)

    assert len(calls) == 1


async def test_the_receipt_still_reports_a_domain_failure(spine) -> None:
    """Parity: the task API's answer is unchanged by any of this."""
    store, admitter = spine
    queue = TaskQueue(admitter=admitter)
    runner = TaskRunner(queue, executor=lambda _req: _completed(_domain_failure()), run_store=store)
    task = await queue.submit(TaskCreate(description="ship it", task_type="code"))

    await runner._execute_task(task.task_id)

    updated = queue.get(task.task_id)
    assert updated is not None
    assert updated.status is TaskStatus.FAILED
    assert updated.result is not None
    assert updated.result.error == "could not find the module"


# ── the same, against the durable store ───────────────────────────


async def test_the_physical_record_is_durable(pg_pool) -> None:
    """The point of #132 applied here: a NodeRun and Attempt a restarted
    process can still read. An execution record that dies with the worker is
    not a record of execution."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore

    workspace = "task-attempt-durable"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    store = PgRunStore(pg_pool, project_store=projects)
    admitter = TaskRunAdmitter(store, workspace_id=workspace, project_id=root.project_id)
    queue = TaskQueue(admitter=admitter)
    task = await queue.submit(TaskCreate(description="ship it", task_type="code"))
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_ok()))

    result = await attempts.execute(
        run_id=task.run_id, task_id=task.task_id, request=_request(task)
    )

    assert result.success
    # A fresh store object, standing in for a restarted process.
    again = PgRunStore(pg_pool, project_store=PgProjectScopeStore(pg_pool))
    node_runs = await again.list_node_runs(task.run_id or "")
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.COMPLETED
    persisted = await again.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in persisted] == [AttemptStatus.COMPLETED]


async def test_a_durable_domain_failure_keeps_the_two_layers_apart(pg_pool) -> None:
    """The distinction has to survive a JSON round-trip, not just live in
    memory: the payload is where the durable store keeps the result."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore

    workspace = "task-attempt-durable-fail"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    store = PgRunStore(pg_pool, project_store=projects)
    admitter = TaskRunAdmitter(store, workspace_id=workspace, project_id=root.project_id)
    queue = TaskQueue(admitter=admitter)
    task = await queue.submit(TaskCreate(description="ship it", task_type="code"))
    attempts = TaskAttemptRunner(store, executor=lambda _req: _completed(_domain_failure()))

    result = await attempts.execute(
        run_id=task.run_id, task_id=task.task_id, request=_request(task)
    )

    assert result.success is False
    node_run = (await store.list_node_runs(task.run_id or ""))[0]
    attempt = (await store.list_attempts(node_run.node_run_id))[0]
    assert attempt.status is AttemptStatus.COMPLETED
    assert node_run.status is RunStatus.FAILED


async def test_the_work_item_carries_the_task_id() -> None:
    """So the physical record traces back to the receipt without a join."""
    item = TaskWorkItem(task_id="t-1", request=TaskCreate(description="x"))

    assert item.task_id == "t-1"


def _request(task: Any) -> TaskCreate:
    return TaskCreate(description=task.description, task_type=task.task_type)


async def _completed(output: ConductorOutput) -> ConductorOutput:
    await asyncio.sleep(0)
    return output
