"""Task submission yields a canonical run_id (#41).

`TaskQueue` has always been its own small lifecycle: submit, claim, transition,
terminal. #41's rule is that the queue row is a *receipt* and the Run is the
execution identity. These tests hold the seam to that: a wired queue produces a
Run before it queues anything, the Run points back at the receipt, and an
admission failure fails the submission rather than quietly producing a task with
no execution identity behind it.
"""

from __future__ import annotations

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import ADMISSION_SOURCE
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.runs.task_kinds import DELEGATE_NODE_KIND
from maistro.tasks.admission import (
    SESSION_ID_KEY,
    TASK_ID_KEY,
    TASK_QUEUE_SOURCE,
    TaskRunAdmitter,
)
from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue, configure_task_queue, get_task_queue


@pytest.fixture
async def scoped():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    project = await projects.create(
        workspace_id="w1", parent_project_id=root.project_id, name="Tasks"
    )
    return projects, InMemoryRunStore(project_store=projects), root, project


async def test_submission_creates_a_run_and_returns_its_id(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )

    task = await queue.submit(TaskCreate(description="Fix the parser", task_type="code"))

    assert task.run_id
    run = await runs.get_run(task.run_id)
    assert run is not None
    assert run.status is RunStatus.CREATED
    assert run.workspace_id == "w1"
    assert run.project_id == project.project_id


async def test_the_run_is_a_one_node_graph_of_the_right_kind(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )

    task = await queue.submit(TaskCreate(description="Fix the parser", task_type="code_gen"))

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    graph = run.graph.materialize()
    assert len(graph.nodes) == 1
    assert graph.edges == []
    node = graph.nodes[0]
    assert node.node_type == DELEGATE_NODE_KIND
    assert node.parameters["to_agent"] == "mason"
    assert node.parameters["task"] == "Fix the parser"


async def test_provenance_correlates_the_run_back_to_its_receipt(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )

    task = await queue.submit(TaskCreate(description="Fix it", session_id="sess-9"), user_id="u1")

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.provenance[ADMISSION_SOURCE] == TASK_QUEUE_SOURCE
    assert run.provenance[TASK_ID_KEY] == task.task_id
    assert run.provenance[SESSION_ID_KEY] == "sess-9"
    assert run.provenance["user_id"] == "u1"
    assert run.actor_principal_id == "u1"
    assert task.session_id == "sess-9"


async def test_absent_session_and_user_are_omitted_rather_than_blank(scoped) -> None:
    """Empty-string provenance is a claim about correlation that isn't true."""
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )

    task = await queue.submit(TaskCreate(description="Fix it"))

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert SESSION_ID_KEY not in run.provenance
    assert "user_id" not in run.provenance
    assert run.actor_principal_id is None


async def test_each_submission_gets_its_own_run(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )

    first = await queue.submit(TaskCreate(description="one"))
    second = await queue.submit(TaskCreate(description="two"))

    assert first.run_id != second.run_id


async def test_the_queued_task_carries_its_run_id(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )

    task = await queue.submit(TaskCreate(description="one"))

    assert queue.get(task.task_id) is not None
    assert queue.get(task.task_id).run_id == task.run_id  # type: ignore[union-attr]


async def test_an_unwired_queue_admits_without_a_run() -> None:
    """The pre-cutover state is explicit, not disguised as an execution identity."""
    queue = TaskQueue()

    task = await queue.submit(TaskCreate(description="one"))

    assert task.run_id is None


async def test_admission_failure_fails_the_submission(scoped) -> None:
    """A task with no Run behind it is the second lifecycle #41 removes."""
    _projects, runs, _root, _project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id="no-such-project")
    )

    with pytest.raises(RunIntegrityError):
        await queue.submit(TaskCreate(description="one"))

    assert queue.list_tasks()[0] == []


async def test_the_root_project_is_resolved_when_none_is_named(scoped) -> None:
    projects, runs, root, _project = scoped
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_store=projects))

    task = await queue.submit(TaskCreate(description="one"))

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.project_id == root.project_id


async def test_the_root_project_is_resolved_once(scoped) -> None:
    projects, runs, _root, _project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_store=projects)
    queue = TaskQueue(admitter=admitter)
    calls = 0
    original = projects.root_for_workspace

    async def counting(workspace_id: str):
        nonlocal calls
        calls += 1
        return await original(workspace_id)

    projects.root_for_workspace = counting  # type: ignore[method-assign]

    await queue.submit(TaskCreate(description="one"))
    await queue.submit(TaskCreate(description="two"))

    assert calls == 1


def test_an_admitter_needs_a_workspace() -> None:
    with pytest.raises(ValueError, match="workspace_id"):
        TaskRunAdmitter(
            InMemoryRunStore(project_store=InMemoryProjectScopeStore()), workspace_id="  "
        )


def test_an_admitter_needs_a_way_to_find_a_project() -> None:
    with pytest.raises(ValueError, match="project"):
        TaskRunAdmitter(
            InMemoryRunStore(project_store=InMemoryProjectScopeStore()), workspace_id="w1"
        )


async def test_configure_task_queue_installs_the_admitter(scoped) -> None:
    """FastAPI routes resolve the singleton, so the admitter has to reach it here."""
    from maistro.tasks import queue as queue_module

    _projects, runs, _root, project = scoped
    previous = queue_module._queue
    queue_module._queue = None
    try:
        installed = configure_task_queue(
            admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
        )

        assert get_task_queue() is installed
        task = await installed.submit(TaskCreate(description="one"))
        assert task.run_id
    finally:
        queue_module._queue = previous


async def test_configure_task_queue_refuses_after_tasks_were_submitted() -> None:
    """A task admitted without a Run cannot be given one afterwards without
    inventing the execution history it never had."""
    from maistro.tasks import queue as queue_module

    previous = queue_module._queue
    queue_module._queue = None
    try:
        await get_task_queue().submit(TaskCreate(description="one"))

        with pytest.raises(RuntimeError, match="cannot be given one"):
            configure_task_queue(admitter=None)
    finally:
        queue_module._queue = previous
