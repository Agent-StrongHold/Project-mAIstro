"""Execution-spine failpoint matrix over the task Attempt path (#883).

`tasks/execution.py` drives one task's work as a physical Attempt under its
Run's single NodeRun. This suite crosses the path's named crash seams with the
canonical recovery and holds the issue's properties in every combination:

* a process killed at any named write leaves durable state the canonical
  recovery halves settle or resume -- the same `reclaim_expired_attempts` +
  `AttemptLifecycleReconciler` pair `Container.recover_abandoned_attempts`
  runs, so the prototype adds no second recovery authority;
* recoverable work resumes exactly where the contract permits -- and where the
  contract forbids redispatch (a completed Attempt awaiting acceptance),
  recovery replays the durable evidence instead of re-running the work;
* terminal state cannot regress, over the whole recorded timeline;
* the receipt (the `/tasks` product surface) eventually agrees with the Run.

Work effects are modeled on a remote ledger so the cells also show the layering
boundary the issue asks about: the execution spine re-runs lost work
(at-least-once); exactly-once external effects are the Invocation ledger's
contract, held in `test_invocation_failpoint_matrix.py`.

A crash is injected through the dispatch seam (`TaskAttemptExecutor` over a
`CrashPoint` store), not through `TaskRunner._execute_task`: the queue's claim
context writes a failure receipt from a `BaseException` handler, and a real
SIGKILL runs no handler. Phase A therefore leaves the receipt exactly where a
killed process would -- mid-flight, unwritten.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest

from maistro.agents.types import CodeOutput, ConductorOutput
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.consumer_claim import ClaimingInMemoryRunStore
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    RunStatus,
)
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import RunIntegrityError
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.execution import TaskAttemptExecutor
from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner

from ._failpoints import (
    CrashPoint,
    CrashSimulated,
    EffectLedger,
    Failpoint,
    JournalingStore,
    StatusJournal,
)

_WORKSPACE = "ws-fp-exec"
_ACTOR = "principal-fp"
_DESCRIPTION = "Fix the parser"
_EFFECT = f"task:{_DESCRIPTION}"
_RESTART_DELAY = timedelta(hours=1)


def _ok() -> ConductorOutput:
    return ConductorOutput(
        success=True,
        final_answer="done",
        code=CodeOutput(description="generated", files_changed=["a.py"]),
    )


class _Work:
    """The task's modeled work: an external effect on a remote system."""

    def __init__(self, remote: EffectLedger, crash: str | None = None) -> None:
        self._remote = remote
        self._crash = crash
        self.calls = 0

    async def __call__(self, request: TaskCreate) -> ConductorOutput:
        self.calls += 1
        if self._crash == "work_effect_before":
            raise CrashSimulated("work_effect", "before")
        self._remote.apply(_EFFECT)
        if self._crash == "work_effect_after":
            raise CrashSimulated("work_effect", "after")
        return _ok()

    def disarm(self) -> None:
        """The restarted process's executor does not crash."""
        self._crash = None


class _Wiring:
    """One scenario's durable store, queue, dispatch seam, and remote ledger."""

    def __init__(
        self,
        crash_at_work: str | None = None,
        *,
        claim_before: bool = False,
        attempt_commit_before: bool = False,
        run_commit_before: bool = False,
    ) -> None:
        self.journal = StatusJournal()
        self.remote = EffectLedger()
        self.work = _Work(self.remote, crash_at_work)
        self.projects = InMemoryProjectScopeStore()
        self.durable = ClaimingInMemoryRunStore(project_store=self.projects)
        self._seam_modes = {
            "claim": claim_before,
            "attempt_terminal_commit": attempt_commit_before,
            "run_terminal_commit": run_commit_before,
        }

    async def submit(self) -> TaskCreate:
        """Admit one task through the queue's canonical admitter."""
        root = await self.projects.create_root(_WORKSPACE)
        journaled = JournalingStore(self.durable, self.journal)
        self.crash = CrashPoint(
            journaled,
            [
                Failpoint("claim", "claim_consumer_run", before=self._seam_modes["claim"]),
                Failpoint(
                    "attempt_terminal_commit",
                    "transition_attempt",
                    when=lambda _attempt_id, status, **_: (
                        str(getattr(status, "value", status)) == "completed"
                    ),
                    before=self._seam_modes["attempt_terminal_commit"],
                ),
                Failpoint(
                    "run_terminal_commit",
                    "transition_run",
                    when=lambda _run_id, status, **_: (
                        str(getattr(status, "value", status))
                        in {"completed", "failed", "cancelled"}
                    ),
                    before=self._seam_modes["run_terminal_commit"],
                ),
            ],
        )
        admitter = TaskRunAdmitter(
            self.durable, workspace_id=_WORKSPACE, project_id=root.project_id
        )
        self.queue = TaskQueue(admitter=admitter)
        return await self.queue.submit(TaskCreate(description=_DESCRIPTION, user_id=_ACTOR))

    def dispatch(self) -> TaskAttemptExecutor:
        """A worker's dispatch seam over the crash-wrapped durable store."""
        return TaskAttemptExecutor(self.crash)

    async def request(self, task: TaskCreate) -> TaskCreate:
        return TaskCreate(description=task.description, user_id=task.user_id)


async def _recovery_tick(store: object, run_id: str, *, now: datetime) -> int:
    """The canonical recovery halves, driven at one later moment.

    What `Container.recover_abandoned_attempts` runs: the lease sweep, each
    reclaimed Attempt through the lifecycle reconciler, then settlement replay
    for terminal Attempts a crash interrupted. Driving the same two canonical
    seams on the scenario's known Run keeps the prototype free of a second
    recovery authority.
    """
    assert isinstance(store, ClaimingInMemoryRunStore)
    touched = 0
    reconciler = AttemptLifecycleReconciler(store)
    for attempt in await store.reclaim_expired_attempts(now=now):
        await reconciler.reconcile(attempt)
        touched += 1
    for node_run in await store.list_node_runs(run_id):
        for attempt in await store.list_attempts(node_run.node_run_id):
            if attempt.status in TERMINAL_ATTEMPT_STATUSES:
                with suppress(RunIntegrityError):
                    await reconciler.reconcile(attempt)
    return touched


async def _recover_and_finish(
    wiring: _Wiring, task: TaskCreate, *, strategy: str = "restart"
) -> TaskQueue:
    """Recover and finish the work; return the queue holding the receipt.

    ``restart`` is a new process: boot recovery (``TaskQueue.recover``)
    rehydrates QUEUED work, the recovery tick settles abandoned Attempts,
    and remaining work re-drives through whichever canonical door applies --
    the worker loop for work the queue rehydrated, the dispatch seam's retry
    path for Runs the reconciler parked WAITING. ``same_process`` is the
    retry-without-restart shape: the live queue reconciles its receipt from
    the terminal Run (#849).
    """
    run_id = task.run_id or ""
    wiring.work.disarm()
    await _recovery_tick(wiring.durable, run_id, now=datetime.now(UTC) + _RESTART_DELAY)
    restarted = TaskQueue()
    if strategy == "restart":
        await restarted.recover(wiring.durable)
    run = await wiring.durable.get_run(run_id)
    assert run is not None
    if run.status not in TERMINAL_RUN_STATUSES:
        if strategy == "restart" and restarted.get(task.task_id) is not None:
            # The queue rehydrated the task: a worker pass drives it.
            runner = TaskRunner(restarted, executor=wiring.work, attempts=wiring.dispatch())
            await runner._execute_task(task.task_id)
        else:
            # A parked Run resumes through the dispatch seam's retry path.
            await wiring.dispatch().execute(run_id, await wiring.request(task), wiring.work)
    if strategy == "same_process":
        await wiring.queue.recover(wiring.durable)
        return wiring.queue
    await restarted.recover(wiring.durable)
    return restarted


def _assert_no_regression(wiring: _Wiring) -> None:
    assert wiring.journal.regressions() == []


# --- the matrix -----------------------------------------------------------


@pytest.mark.parametrize("mode", ["before", "after"])
async def test_claim_seam(mode: str) -> None:
    """Crash at the atomic claim: before it, the Run is still QUEUED."""
    wiring = _Wiring(claim_before=(mode == "before"))
    task = await wiring.submit()
    wiring.crash.arm("claim")

    with pytest.raises(CrashSimulated):
        await wiring.dispatch().execute(task.run_id or "", await wiring.request(task), wiring.work)
    assert wiring.crash.fired == [("claim", mode)]

    run = await wiring.durable.get_run(task.run_id or "")
    assert run is not None
    if mode == "before":
        assert run.status is RunStatus.QUEUED
    else:
        # The claim is atomic: RUNNING always arrives with the NodeRun and the
        # leased Attempt that make it true (#1114). The work never ran.
        assert run.status is RunStatus.RUNNING
        assert wiring.work.calls == 0

    restarted = await _recover_and_finish(wiring, task)

    run = await wiring.durable.get_run(task.run_id or "")
    assert run is not None and run.status is RunStatus.COMPLETED
    node_runs = await wiring.durable.list_node_runs(task.run_id or "")
    assert len(node_runs) == 1
    if mode == "before":
        # QUEUED work rehydrates into the restarted queue, so its worker loop
        # finishes the task and writes the receipt it owns.
        receipt = restarted.get(task.task_id)
        assert receipt is not None and receipt.status.value == "completed"
    else:
        # A claimed-but-unworked Run parks WAITING and resumes through the
        # dispatch seam; on the in-memory tier the receipt lived in the dead
        # process, and the durable Run is the truth recovery can offer.
        assert restarted.get(task.task_id) is None
    assert wiring.journal.regressions() == []


@pytest.mark.parametrize("crash_at", ["work_effect_before", "work_effect_after"])
@pytest.mark.parametrize("strategy", ["restart", "same_process"])
async def test_work_loss_seam(crash_at: str, strategy: str) -> None:
    """The process dies inside the executor, with or without the effect applied."""
    wiring = _Wiring(crash_at_work=crash_at)
    task = await wiring.submit()

    with pytest.raises(CrashSimulated):
        await wiring.dispatch().execute(task.run_id or "", await wiring.request(task), wiring.work)
    assert wiring.remote.count(_EFFECT) == (1 if crash_at == "work_effect_after" else 0)

    holder = await _recover_and_finish(wiring, task, strategy=strategy)

    run = await wiring.durable.get_run(task.run_id or "")
    assert run is not None and run.status is RunStatus.COMPLETED
    node_runs = await wiring.durable.list_node_runs(task.run_id or "")
    assert len(node_runs) == 1
    attempts = await wiring.durable.list_attempts(node_runs[0].node_run_id)
    assert [a.ordinal for a in attempts] == [1, 2]
    receipt = holder.get(task.task_id)
    if strategy == "same_process":
        # The live queue reconciles its receipt from the terminal Run (#849).
        assert receipt is not None and receipt.status.value == "completed"
    else:
        assert receipt is None
    assert wiring.journal.regressions() == []

    if crash_at == "work_effect_after":
        # The documented layering boundary: the execution spine re-runs work
        # whose result was lost with the process (at-least-once). Exactly-once
        # is the Invocation ledger's contract, not this seam's.
        assert wiring.remote.count(_EFFECT) == 2
    else:
        assert wiring.remote.count(_EFFECT) == 1


@pytest.mark.parametrize("mode", ["before", "after"])
async def test_attempt_terminal_commit_is_replayed_not_rerun(mode: str) -> None:
    """Attempt COMPLETED (or its write lost), acceptance interrupted.

    ``before`` kills the Attempt's own terminal write -- the work applied
    remotely but the Attempt still reads RUNNING, so the lease sweep reclaims
    it and the retry re-runs the work. ``after`` lands the write -- the durable
    Attempt now holds the result, the spine refuses redispatch while a
    completed Attempt awaits acceptance, and the reconciler replays the
    evidence instead. Only the second cell protects an external effect under a
    naive "just re-dispatch" recovery; the first is the documented
    at-least-once boundary.
    """
    wiring = _Wiring(attempt_commit_before=(mode == "before"))
    task = await wiring.submit()
    wiring.crash.arm("attempt_terminal_commit")

    with pytest.raises(CrashSimulated):
        await wiring.dispatch().execute(task.run_id or "", await wiring.request(task), wiring.work)
    assert wiring.crash.fired == [("attempt_terminal_commit", mode)]
    assert wiring.remote.count(_EFFECT) == 1

    await _recover_and_finish(wiring, task)

    run = await wiring.durable.get_run(task.run_id or "")
    assert run is not None and run.status is RunStatus.COMPLETED
    node_runs = await wiring.durable.list_node_runs(task.run_id or "")
    (node_run,) = node_runs
    assert node_run.accepted_outcome is not None
    if mode == "after":
        # No second physical try: the evidence replay finished the Run.
        assert wiring.work.calls == 1
    else:
        assert wiring.work.calls == 2
    assert wiring.remote.count(_EFFECT) == (1 if mode == "after" else 2)
    _assert_no_regression(wiring)


@pytest.mark.parametrize("mode", ["before", "after"])
async def test_run_terminal_commit_seam(mode: str) -> None:
    """Crash at the Run's settlement, and receipt reconciliation after it."""
    wiring = _Wiring(run_commit_before=(mode == "before"))
    task = await wiring.submit()
    wiring.crash.arm("run_terminal_commit")

    with pytest.raises(CrashSimulated):
        await wiring.dispatch().execute(task.run_id or "", await wiring.request(task), wiring.work)
    assert wiring.crash.fired == [("run_terminal_commit", mode)]

    await _recover_and_finish(wiring, task)

    run = await wiring.durable.get_run(task.run_id or "")
    assert run is not None and run.status is RunStatus.COMPLETED
    assert wiring.work.calls == 1  # settled from evidence, not re-run
    node_runs = await wiring.durable.list_node_runs(task.run_id or "")
    (node_run,) = node_runs
    assert node_run.accepted_outcome is not None
    _assert_no_regression(wiring)
