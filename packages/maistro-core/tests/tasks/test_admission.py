"""Task submission yields a canonical run_id (#41).

`TaskQueue` has always been its own small lifecycle: submit, claim, transition,
terminal. #41's rule is that the queue row is a *receipt* and the Run is the
execution identity. These tests hold the seam to that: a wired queue produces a
Run before it queues anything, the Run points back at the receipt, and an
admission failure fails the submission rather than quietly producing a task with
no execution identity behind it.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.observability.correlation import bind_execution_context
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import ADMISSION_SOURCE, admit_direct_work
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.runs.task_kinds import DELEGATE_NODE_KIND
from maistro.tasks.admission import (
    REQUEST_ID_KEY,
    SESSION_ID_KEY,
    TASK_ID_KEY,
    TASK_PAYLOAD_KEY,
    TASK_QUEUE_SOURCE,
    TaskRunAdmitter,
)
from maistro.tasks.models import TaskCreate, TaskStatus
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
    assert run.status is RunStatus.QUEUED
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


async def test_the_run_contains_the_restart_payload(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )
    submitted = TaskCreate(
        description="restart me",
        workspace="/tmp/workspace",
        branch="feature/restart",
        constraints=["run tests"],
        program_context={"ticket": "1114"},
    )
    task = await queue.submit(submitted)
    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status is RunStatus.QUEUED
    assert run.provenance[TASK_PAYLOAD_KEY]["description"] == submitted.description
    assert run.provenance[TASK_PAYLOAD_KEY]["branch"] == submitted.branch
    assert run.provenance[TASK_PAYLOAD_KEY]["constraints"] == submitted.constraints


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


async def test_the_bound_request_id_lands_on_the_runs_provenance(scoped) -> None:
    """#1063: the Conductor->maistro-server hop, the Task, and the Run must be
    followable by one correlation id. `admit()` runs inside the same coroutine
    chain RequestIDMiddleware bound the id in (or whatever a background
    caller explicitly bound), so reading it off the ambient context — rather
    than adding a `request_id` field to `TaskCreate` — is enough."""
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )

    with bind_execution_context(request_id="req-xyz"):
        task = await queue.submit(TaskCreate(description="Fix it"))

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.provenance[REQUEST_ID_KEY] == "req-xyz"


async def test_no_bound_request_id_is_omitted_rather_than_blank(scoped) -> None:
    """Same discipline as session/user: absence states the truth, an empty
    string would claim a request correlation that was never established."""
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )

    task = await queue.submit(TaskCreate(description="Fix it"))

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert REQUEST_ID_KEY not in run.provenance


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


async def test_a_new_queue_rehydrates_a_queued_run(scoped) -> None:
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    original = TaskQueue(admitter=admitter)
    submitted = await original.submit(
        TaskCreate(description="recover me", branch="restart", constraints=["tests"])
    )

    restarted = TaskQueue()
    assert await restarted.recover(runs) == 1
    recovered = restarted.get(submitted.task_id)
    assert recovered is not None
    assert recovered.run_id == submitted.run_id
    assert recovered.description == submitted.description
    assert recovered.branch == "restart"
    assert recovered.constraints == ["tests"]
    assert await restarted.next_task() == submitted.task_id


async def test_death_after_run_admission_is_recoverable(scoped) -> None:
    _projects, runs, _root, project = scoped
    delegate = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)

    class _ProcessDeath(BaseException):
        pass

    class _CrashAfterAdmission:
        async def admit(self, task, *, workspace_id=None):
            run_id = await delegate.admit(task, workspace_id=workspace_id)
            raise _ProcessDeath(run_id)

        async def record_transition(self, run_id, status, **kwargs):
            return await delegate.record_transition(run_id, status, **kwargs)

    with pytest.raises(_ProcessDeath):
        await TaskQueue(admitter=_CrashAfterAdmission()).submit(
            TaskCreate(description="death after admission")
        )

    restarted = TaskQueue(admitter=delegate)
    assert await restarted.recover(runs) == 1
    assert await restarted.next_task()


async def test_death_after_receipt_before_notification_is_recoverable(scoped) -> None:
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)

    class _ProcessDeath(BaseException):
        pass

    class _CrashQueue:
        async def put(self, _task_id):
            raise _ProcessDeath

    queue = TaskQueue(admitter=admitter)
    queue._pending = _CrashQueue()  # type: ignore[assignment]
    with pytest.raises(_ProcessDeath):
        await queue.submit(TaskCreate(description="death before notification"))

    restarted = TaskQueue(admitter=admitter)
    assert await restarted.recover(runs) == 1
    assert await restarted.next_task()


async def test_recovered_task_runs_under_the_original_canonical_identity(scoped) -> None:
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    submitted = await TaskQueue(admitter=admitter).submit(
        TaskCreate(description="execute after restart")
    )

    restarted = TaskQueue(admitter=admitter)
    assert await restarted.recover(runs) == 1

    from maistro.agents.types import ConductorOutput
    from maistro.tasks.execution import TaskAttemptExecutor
    from maistro.tasks.runner import TaskRunner

    async def execute(request: TaskCreate) -> ConductorOutput:
        return ConductorOutput(success=True, final_answer=request.description)

    await TaskRunner(
        restarted,
        execute,
        attempts=TaskAttemptExecutor(runs),
    )._execute_task(submitted.task_id)

    recovered = restarted.get(submitted.task_id)
    assert recovered is not None and recovered.status is TaskStatus.COMPLETED
    run = await runs.get_run(submitted.run_id or "")
    assert run is not None and run.status is RunStatus.COMPLETED
    node_runs = await runs.list_node_runs(submitted.run_id or "")
    assert len(node_runs) == 1
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status.value == "completed"


async def test_two_recovery_receipts_have_one_canonical_transition_winner(scoped) -> None:
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    original = TaskQueue(admitter=admitter)
    submitted = await original.submit(TaskCreate(description="race me"))
    first, second = TaskQueue(admitter=admitter), TaskQueue(admitter=admitter)
    assert await first.recover(runs) == 1
    assert await second.recover(runs) == 1

    assert await first.update_status(submitted.task_id, TaskStatus.PLANNING)
    assert not await second.update_status(submitted.task_id, TaskStatus.PLANNING)
    run = await runs.get_run(submitted.run_id or "")
    assert run is not None and run.status is RunStatus.RUNNING


async def test_malformed_recovery_payload_fails_the_canonical_run(scoped) -> None:
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    original = TaskQueue(admitter=admitter)
    submitted = await original.submit(TaskCreate(description="malformed"))
    stored = runs._runs[submitted.run_id or ""]  # type: ignore[attr-defined]
    stored.provenance.pop(TASK_PAYLOAD_KEY)

    restarted = TaskQueue()
    assert await restarted.recover(runs) == 0
    run = await runs.get_run(submitted.run_id or "")
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error is not None and "missing durable task payload" in run.error


async def test_recovery_rejects_a_payload_whose_task_id_disagrees(scoped) -> None:
    """A payload naming another receipt is corrupted evidence, not this Run's
    input: terminalize the Run instead of executing under the wrong identity."""
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    submitted = await TaskQueue(admitter=admitter).submit(TaskCreate(description="swapped"))
    stored = runs._runs[submitted.run_id or ""]  # type: ignore[attr-defined]
    stored.provenance[TASK_ID_KEY] = "a-different-receipt"

    restarted = TaskQueue()
    assert await restarted.recover(runs) == 0
    run = await runs.get_run(submitted.run_id or "")
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error is not None and "invalid durable task payload" in run.error


async def test_recovery_rejects_a_payload_that_is_not_queued(scoped) -> None:
    """A snapshot claiming a live status contradicts the QUEUED Run it rode in
    on; recovery must not resurrect a task from a half-updated snapshot."""
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    submitted = await TaskQueue(admitter=admitter).submit(TaskCreate(description="phantom"))
    stored = runs._runs[submitted.run_id or ""]  # type: ignore[attr-defined]
    payload = stored.provenance[TASK_PAYLOAD_KEY]
    payload["status"] = TaskStatus.PLANNING.value
    stored.provenance[TASK_PAYLOAD_KEY] = payload

    restarted = TaskQueue()
    assert await restarted.recover(runs) == 0
    run = await runs.get_run(submitted.run_id or "")
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error is not None and "invalid durable task payload" in run.error


async def test_recovery_of_a_store_without_queued_runs_is_a_no_op(scoped) -> None:
    """Restarting with nothing stranded starts no work and raises nothing."""
    _projects, runs, _root, _project = scoped
    restarted = TaskQueue()

    assert await restarted.recover(runs) == 0
    assert restarted._pending.empty()  # type: ignore[attr-defined]
    assert restarted.list_tasks()[0] == []


async def test_recovery_rejects_a_non_positive_batch_size(scoped) -> None:
    """A non-positive page size is a caller bug, not an empty scan."""
    _projects, runs, _root, _project = scoped
    restarted = TaskQueue()

    with pytest.raises(ValueError, match="batch_size"):
        await restarted.recover(runs, batch_size=0)


async def test_recovery_ignores_queued_runs_from_other_admission_sources(scoped) -> None:
    """QUEUED Runs admitted by another source are owned by their own consumer
    (#251); the task queue must not steal them into a second lifecycle."""
    _projects, runs, root, _project = scoped
    await admit_direct_work(
        runs,
        workspace_id="w1",
        project_id=root.project_id,
        node_type=DELEGATE_NODE_KIND,
        name="scheduled work",
        source="schedule",
        initial_status=RunStatus.QUEUED,
    )

    restarted = TaskQueue()
    assert await restarted.recover(runs) == 0
    queued = await runs.list_by_status(RunStatus.QUEUED)
    assert len(queued) == 1
    assert queued[0].status is RunStatus.QUEUED


async def test_recovery_does_not_double_enqueue_a_receipt_still_in_memory(scoped) -> None:
    """Recovery racing normal delivery must not deliver the task twice: the
    receipt already in memory is the one dispatch intent for this process."""
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    queue = TaskQueue(admitter=admitter)
    submitted = await queue.submit(TaskCreate(description="still here"))

    assert await queue.recover(runs) == 0
    assert await queue.next_task() == submitted.task_id
    assert queue._pending.empty()  # type: ignore[attr-defined]


class _RefusingStore:
    """Delegates enumeration but refuses chosen transitions, the way a store
    claimed by a concurrent worker (or a store mid-fault) would."""

    def __init__(
        self,
        store: Any,
        *,
        refuse_running: bool = False,
        refuse_failed: bool = False,
    ) -> None:
        self._store = store
        self._refuse_running = refuse_running
        self._refuse_failed = refuse_failed

    async def list_by_status(self, status: Any, **kwargs: Any) -> Any:
        return await self._store.list_by_status(status, **kwargs)

    async def transition_run(self, run_id: str, target: Any, **kwargs: Any) -> Any:
        if target is RunStatus.RUNNING and self._refuse_running:
            raise RuntimeError("run claimed by a concurrent worker")
        if target is RunStatus.FAILED and self._refuse_failed:
            raise RuntimeError("terminal write refused")
        return await self._store.transition_run(run_id, target, **kwargs)


async def test_recovery_yields_the_run_a_worker_already_claimed(scoped) -> None:
    """The canonical claim is the fence: when another worker already moved the
    Run out of QUEUED, recovery records no failure and leaves the outcome to
    the owner. One Attempt chain, two would-be dispatchers."""
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    submitted = await TaskQueue(admitter=admitter).submit(TaskCreate(description="claimed"))
    stored = runs._runs[submitted.run_id or ""]  # type: ignore[attr-defined]
    stored.provenance.pop(TASK_PAYLOAD_KEY)

    obstacle = _RefusingStore(runs, refuse_running=True)
    restarted = TaskQueue()
    assert await restarted.recover(obstacle) == 0
    run = await runs.get_run(submitted.run_id or "")
    assert run is not None
    assert run.status is RunStatus.QUEUED


async def test_recovery_survives_a_refused_terminalization(scoped) -> None:
    """A store that refuses the FAILED write must not crash recovery of the
    remaining runs; the claimed Run is no longer QUEUED, so it cannot strand."""
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    submitted = await TaskQueue(admitter=admitter).submit(TaskCreate(description="stuck"))
    stored = runs._runs[submitted.run_id or ""]  # type: ignore[attr-defined]
    stored.provenance.pop(TASK_PAYLOAD_KEY)

    obstacle = _RefusingStore(runs, refuse_failed=True)
    restarted = TaskQueue()
    assert await restarted.recover(obstacle) == 0
    run = await runs.get_run(submitted.run_id or "")
    assert run is not None
    assert run.status is RunStatus.RUNNING


async def test_postgres_queued_task_rehydrates_after_queue_restart(pg_pool) -> None:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.consumer_claim import ClaimingPgRunStore

    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root("pg-recovery")
    runs = ClaimingPgRunStore(pg_pool, project_store=projects)
    admitter = TaskRunAdmitter(runs, workspace_id="pg-recovery", project_id=root.project_id)
    submitted = await TaskQueue(admitter=admitter).submit(
        TaskCreate(description="recover from PostgreSQL")
    )

    restarted = TaskQueue(admitter=admitter)
    assert await restarted.recover(runs) == 1
    recovered = restarted.get(submitted.task_id)
    assert recovered is not None and recovered.run_id == submitted.run_id
    assert await restarted.next_task() == submitted.task_id


async def test_postgres_death_after_run_admission_executes_original_identity(
    pg_pool,
) -> None:
    """Crash at boundary 1 against the durable store: the process dies after
    the QUEUED Run (payload included) is committed and before any receipt
    exists. Recovery from PostgreSQL alone must put the task back under its
    original Run/NodeRun/Attempt chain, not mint a replacement Run."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.agents.types import ConductorOutput
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.consumer_claim import ClaimingPgRunStore
    from maistro.tasks.execution import TaskAttemptExecutor
    from maistro.tasks.runner import TaskRunner

    class _ProcessDeath(BaseException):
        pass

    class _CrashAfterAdmission:
        """The worker died between admit() and the in-memory insertion."""

        def __init__(self, delegate: TaskRunAdmitter) -> None:
            self._delegate = delegate

        async def admit(self, task: Any, *, workspace_id: Any = None) -> str:
            run_id = await self._delegate.admit(task, workspace_id=workspace_id)
            raise _ProcessDeath(run_id)

        async def record_transition(self, run_id: Any, status: Any, **kwargs: Any) -> bool:
            return await self._delegate.record_transition(run_id, status, **kwargs)

    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root("pg-crash-admission")
    runs = ClaimingPgRunStore(pg_pool, project_store=projects)
    delegate = TaskRunAdmitter(runs, workspace_id="pg-crash-admission", project_id=root.project_id)
    with pytest.raises(_ProcessDeath):
        await TaskQueue(admitter=_CrashAfterAdmission(delegate)).submit(
            TaskCreate(description="pg death after admission")
        )

    # The restarted process rehydrates from the durable QUEUED Run and the
    # task executes under the identity the original admission created.
    restarted = TaskQueue(admitter=delegate)
    assert await restarted.recover(runs) == 1
    queued = restarted.list_tasks()[0]
    assert len(queued) == 1 and queued[0].run_id is not None
    task_id = queued[0].task_id
    run_id = queued[0].run_id

    async def execute(request: TaskCreate) -> ConductorOutput:
        return ConductorOutput(success=True, final_answer=request.description)

    await TaskRunner(
        restarted,
        execute,
        attempts=TaskAttemptExecutor(runs),
    )._execute_task(task_id)

    run = await runs.get_run(run_id or "")
    assert run is not None and run.status is RunStatus.COMPLETED
    node_runs = await runs.list_node_runs(run_id or "")
    assert len(node_runs) == 1
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status.value == "completed"


async def test_postgres_malformed_admission_gets_a_terminal_disposition(pg_pool) -> None:
    """Crash-boundary recovery against the durable store must never leave an
    immortal QUEUED Run: a payload PostgreSQL cannot honor is claimed and
    failed visibly on the canonical Run."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.consumer_claim import ClaimingPgRunStore

    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root("pg-crash-malformed")
    runs = ClaimingPgRunStore(pg_pool, project_store=projects)
    admitter = TaskRunAdmitter(runs, workspace_id="pg-crash-malformed", project_id=root.project_id)
    submitted = await TaskQueue(admitter=admitter).submit(TaskCreate(description="pg malformed"))

    # Simulate the corruption a hand-edited or partially-migrated row leaves:
    # the Run is QUEUED and task-sourced, but its durable payload is gone.
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """UPDATE canonical_runs
                  SET payload = jsonb_set(payload, '{provenance}', (payload->'provenance') - $2)
                WHERE run_id = $1""",
            submitted.run_id,
            TASK_PAYLOAD_KEY,
        )

    restarted = TaskQueue()
    assert await restarted.recover(runs) == 0
    run = await runs.get_run(submitted.run_id or "")
    assert run is not None and run.status is RunStatus.FAILED
    assert run.error is not None and "missing durable task payload" in run.error


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


async def test_the_run_advances_with_the_task(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )
    task = await queue.submit(TaskCreate(description="one"))

    await queue.update_status(task.task_id, TaskStatus.PLANNING)

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status is RunStatus.RUNNING


async def test_task_phases_are_one_running_run(scoped) -> None:
    """planning/coding/reviewing/testing are phases of one execution, not four."""
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )
    task = await queue.submit(TaskCreate(description="one"))

    for status in (
        TaskStatus.PLANNING,
        TaskStatus.CODING,
        TaskStatus.REVIEWING,
        TaskStatus.TESTING,
    ):
        assert await queue.update_status(task.task_id, status) is True

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status is RunStatus.RUNNING


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ((TaskStatus.PLANNING, TaskStatus.CODING, TaskStatus.COMPLETED), RunStatus.COMPLETED),
        ((TaskStatus.PLANNING, TaskStatus.FAILED), RunStatus.FAILED),
        ((TaskStatus.CANCELLED,), RunStatus.CANCELLED),
    ],
)
async def test_terminal_task_states_are_terminal_run_states(scoped, path, expected) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )
    task = await queue.submit(TaskCreate(description="one"))

    for status in path:
        assert await queue.update_status(task.task_id, status) is True

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.status is expected


async def test_a_run_that_refuses_refuses_the_task_too(scoped) -> None:
    """The point of "the Run is authoritative": the receipt cannot record a
    state the execution identity rejected."""
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )
    task = await queue.submit(TaskCreate(description="one"))
    # Cancel the Run out from under the receipt, which the task machine knows
    # nothing about — nothing else can then advance it.
    await runs.transition_run(task.run_id or "", RunStatus.CANCELLED)

    assert await queue.update_status(task.task_id, TaskStatus.PLANNING) is False
    assert queue.get(task.task_id).status is TaskStatus.QUEUED  # type: ignore[union-attr]


async def test_an_unwired_queue_transitions_as_before() -> None:
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="one"))

    assert await queue.update_status(task.task_id, TaskStatus.PLANNING) is True


# ── the Run carries the outcome, not just the status ──────────────


async def test_a_completed_run_carries_its_result(scoped) -> None:
    """A caller who follows the run_id must learn how the work ended, not only
    that it did. Passing the outcome to `set_result` alone left every terminal
    Run reporting result=None forever."""
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )
    task = await queue.submit(TaskCreate(description="one"))
    await queue.update_status(task.task_id, TaskStatus.PLANNING)
    await queue.update_status(task.task_id, TaskStatus.CODING)

    await queue.update_status(
        task.task_id, TaskStatus.COMPLETED, result={"files_changed": ["a.py"]}
    )

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.result == {"files_changed": ["a.py"]}


async def test_a_failed_run_carries_its_error(scoped) -> None:
    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    )
    task = await queue.submit(TaskCreate(description="one"))
    await queue.update_status(task.task_id, TaskStatus.PLANNING)

    await queue.update_status(task.task_id, TaskStatus.FAILED, error="the tool exploded")

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.error == "the tool exploded"


async def test_a_receipt_whose_run_vanished_cannot_advance(scoped) -> None:
    """An orphaned identity. Treating a missing Run as success made "no Run"
    indistinguishable from "already in that state", which is the divergence this
    seam exists to prevent."""
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    queue = TaskQueue(admitter=admitter)
    task = await queue.submit(TaskCreate(description="one"))

    assert await admitter.record_transition("no-such-run", TaskStatus.PLANNING) is False
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING) is True


async def test_the_admitter_uses_the_registry_it_was_given(scoped) -> None:
    """A separately-built default registry disagreed with the container's, so a
    PM-mode deployment recorded an engineering agent in the canonical Graph."""
    from maistro.agents.intents import IntentRegistry

    _projects, runs, _root, project = scoped
    queue = TaskQueue(
        admitter=TaskRunAdmitter(
            runs,
            workspace_id="w1",
            project_id=project.project_id,
            intents=IntentRegistry({"delivery": "delivery"}),
        )
    )

    task = await queue.submit(TaskCreate(description="ship it", task_type="delivery"))

    run = await runs.get_run(task.run_id or "")
    assert run is not None
    assert run.graph.materialize().nodes[0].parameters["to_agent"] == "delivery"


async def test_a_run_that_left_waiting_under_us_does_not_falsely_report_progress(
    scoped,
) -> None:
    """The resume before terminalizing is a second write, and it can lose.

    `record_transition` reads the Run, sees WAITING, and resumes it to RUNNING
    so a terminal target has an edge to travel (#143). Between that read and
    that write another worker can move the same Run — a cancellation, a
    timeout — and the resume is then illegal. Reporting success there would
    tell the queue the receipt advanced when the Run did not.
    """
    _projects, runs, _root, project = scoped
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    queue = TaskQueue(admitter=admitter)
    task = await queue.submit(TaskCreate(description="one"))
    run_id = task.run_id or ""
    await runs.transition_run(run_id, RunStatus.RUNNING)
    await runs.transition_run(run_id, RunStatus.WAITING)

    real_transition = runs.transition_run
    lost_the_race = False

    async def _losing(run_id_: str, target: RunStatus, **kwargs: object):
        nonlocal lost_the_race
        if target is RunStatus.RUNNING and not lost_the_race:
            lost_the_race = True
            # The competing worker's write, which is what makes ours illegal.
            await real_transition(run_id_, RunStatus.CANCELLED)
        return await real_transition(run_id_, target, **kwargs)

    runs.transition_run = _losing  # type: ignore[method-assign]

    assert await admitter.record_transition(run_id, TaskStatus.FAILED) is False
    runs.transition_run = real_transition  # type: ignore[method-assign]
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.CANCELLED
