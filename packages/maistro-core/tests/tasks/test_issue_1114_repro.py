"""#1114 regression: recovery derives dispatchability from durable facts alone.

A process death between the durable QUEUED Run commit and the in-memory
receipt insertion leaves a canonical Run that no living process has any
receipt for. These tests reproduce exactly that shape — the Run is admitted
through the production `TaskRunAdmitter.admit()` write (the same one that
persists payload and task_id provenance with the QUEUED Run), and then every
in-memory trace of the submission is discarded — and require a bare
`TaskQueue` with no admitter wired and no shared state to rebuild the receipt
and the dispatch intent from the Run alone. Nothing here hands the restarted
queue the task_id, the payload, or an admitter: if recovery needed anything
that is not a durable canonical fact, the stranded window would still exist.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TASK_QUEUE_SOURCE, TaskRunAdmitter
from maistro.tasks.models import TaskStatus
from maistro.tasks.queue import TaskQueue


@pytest.fixture
async def durable_run():
    """Admit one task through the production write, then lose the process.

    Returns (run_store, task) where `task` is the receipt the dying process
    held only in memory — nothing about it survives in the store except the
    Run's provenance.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    project = await projects.create(
        workspace_id="w1", parent_project_id=root.project_id, name="Tasks"
    )
    runs = InMemoryRunStore(project_store=projects)
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)

    # The receipt as `TaskQueue.submit` mints it, immediately before admit().
    from maistro.tasks.models import TaskResponse

    task = TaskResponse(
        task_id=TaskResponse.new_id(),
        status=TaskStatus.QUEUED,
        description="durable-only dispatch after restart",
        workspace="w1",
        tier=2,
        created_at=datetime.now(UTC),
    )
    task.run_id = await admitter.admit(task, workspace_id="w1")
    # ...process death here: `_tasks[task_id] = task` and
    # `_pending.put(task_id)` never happened anywhere.
    return runs, task


async def test_a_run_with_no_living_receipt_is_recovered_from_durable_facts(
    durable_run,
) -> None:
    runs, lost = durable_run

    # A bare restarted queue: no admitter, no idempotency store, empty memory.
    restarted = TaskQueue()
    assert not restarted._tasks
    assert restarted._pending.empty()

    assert await restarted.recover(runs) == 1

    receipt = restarted.get(lost.task_id)
    assert receipt is not None
    assert receipt.run_id == lost.run_id
    assert receipt.status is TaskStatus.QUEUED
    assert receipt.description == lost.description
    # Dispatch intent is rebuilt, not just the receipt.
    assert await restarted._pending.get() == lost.task_id


async def test_recovered_dispatchability_is_anchored_on_the_canonical_run(
    durable_run,
) -> None:
    runs, lost = durable_run

    run = await runs.get_run(lost.run_id or "")
    assert run is not None
    assert run.status is RunStatus.QUEUED
    assert run.provenance["admission_source"] == TASK_QUEUE_SOURCE
    assert run.provenance["task_id"] == lost.task_id
    assert run.provenance["task_payload"]["description"] == lost.description

    restarted = TaskQueue()
    assert await restarted.recover(runs) == 1
    # The rehydrated receipt is the durable payload, not the caller's memory.
    assert restarted.get(lost.task_id) is not None
    assert restarted.get("never-admitted") is None
