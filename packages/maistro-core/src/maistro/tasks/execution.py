"""Running one queued task as a canonical Attempt (#143).

#41 gave every submitted task a Run. Execution did not follow it: the runner
called its injected executor directly, so the Run's one Graph node had no
NodeRun, no Attempt, and no record of when the physical try started, what ran
it, how long it took, or which try this was. `GET /v1/runs/{id}/node-runs` was
an endpoint that was correct and always empty.

The seam already existed — `maistro.runs.service.RunExecutionService` — and
nothing in this package called it. This module is the adapter that does, and it
lives on the tasks side for the same reason `tasks/admission.py` does: the runs
package must not learn the shape of every entry point that will feed it.

## The distinction this module exists to preserve

An Attempt is a *physical* execution. A NodeRun and a Run are *logical* work.
The conductor returns `ConductorOutput(success=False)` for work it ran to
completion and could not do — a logical failure whose physical execution
finished normally. Recording that Attempt as FAILED would collapse the two
layers the spine exists to separate, and would make a crashed process
indistinguishable from an honest "I couldn't".

So a returned `ConductorOutput` always completes its Attempt, and the logical
disposition is assigned explicitly via `AcceptedNodeOutcome` — which is exactly
what `AttemptExecutionService`'s `reconcile_logical=False` is documented for,
and why `FAILED` is in `ACCEPTED_NODE_OUTCOME_STATUSES`.

A raised exception is a physical failure and stays one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    AttemptResult,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.service import RunExecutionService
from maistro.runs.store import RunIntegrityError
from maistro.runtime import PythonExecutionRuntime

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Coroutine

    from maistro.agents.types import ConductorOutput
    from maistro.runs.store import RunStore
    from maistro.runtime import ExecutionRuntime
    from maistro.tasks.models import TaskCreate

#: `executor_id` recorded on every Attempt this module creates. It also becomes
#: the Attempt's lease holder, so a recovery scan can tell task-runner work from
#: graph traversal without reading the Run's provenance.
TASK_EXECUTOR_ID = "task_runner"


def _as_conductor_output(value: Any) -> ConductorOutput:
    """The Attempt's persisted result, back as the model the runner expects.

    A store that round-trips its payload through JSON hands back a dict, and a
    store that keeps the object hands back the object. Both are correct; the
    caller should not have to know which store it got.
    """
    from maistro.agents.types import ConductorOutput as _ConductorOutput

    if isinstance(value, _ConductorOutput):
        return value
    return _ConductorOutput.model_validate(value)


@dataclass(frozen=True)
class TaskWorkItem:
    """The opaque work item the Runtime carries for one task execution.

    Runtime treats this as a value and never interprets it (ADR-081426-1f7c);
    only the executor below unpacks it. `task_id` rides along because the
    physical record should be traceable back to the receipt without a join
    through the Run.
    """

    task_id: str
    request: TaskCreate


class TaskAttemptRunner:
    """Execute one queued task as a NodeRun and Attempt under its canonical Run."""

    def __init__(
        self,
        run_store: RunStore,
        *,
        executor: Callable[[TaskCreate], Coroutine[Any, Any, ConductorOutput]],
        runtime: ExecutionRuntime | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._store = run_store
        self._executor = executor
        self._timeout_s = timeout_s
        self._service = RunExecutionService(
            store=run_store,
            runtime=runtime if runtime is not None else PythonExecutionRuntime(),
        )

    async def _runtime_executor(self, work_item: Any, _context: Any) -> ConductorOutput:
        """The `ExecutionCallable` Runtime invokes. Unpacks, delegates, returns."""
        return await self._executor(work_item.request)

    async def _node_id(self, run: Run) -> str:
        """The single node of a directly-submitted task's Graph.

        Admission builds exactly one (`runs/admission.direct_work_graph`). A Run
        that has more is not a task Run, and executing its first node as if it
        were would silently run the wrong work.
        """
        nodes = run.graph.materialize().nodes
        if len(nodes) != 1:
            raise RunIntegrityError(
                f"task Run {run.run_id!r} has {len(nodes)} Graph nodes; a directly-submitted "
                "task admits exactly one"
            )
        return nodes[0].node_id

    async def execute(self, *, run_id: str, task_id: str, request: TaskCreate) -> ConductorOutput:
        """Run one task through the canonical seam and return its domain result.

        Raises whatever the executor raised, after the Attempt has recorded the
        physical failure. The caller keeps its existing handling — the runner
        already turns an exception into a FAILED receipt — and now the spine
        agrees with it.
        """
        run = await self._store.get_run(run_id)
        if run is None:
            raise RunIntegrityError(f"task Run {run_id!r} does not exist")
        node_id = await self._node_id(run)
        work_item = TaskWorkItem(task_id=task_id, request=request)

        try:
            node_run, attempt = await self._service.execute_node(
                run_id,
                node_id,
                work_item,
                None,
                executor=self._runtime_executor,
                executor_id=TASK_EXECUTOR_ID,
                timeout_s=self._timeout_s,
                # The whole point: a completed Attempt does not yet mean the
                # work succeeded, and only this layer knows the difference.
                reconcile_logical=False,
            )
        except Exception:
            # The Attempt is already terminal and the reconciler has parked the
            # NodeRun and the Run in WAITING. The task domain has no retry
            # policy, so WAITING is not a state anything will ever move it out
            # of — terminalize here or leave a Run that looks live forever.
            await self._fail_parked(run_id)
            raise

        # Re-read rather than use the Attempt in hand. The two differ on a
        # durable store: the returned object still holds the live
        # `ConductorOutput`, while the persisted payload has been through JSON
        # and comes back as a dict. `accept_outcome` compares the accepted
        # evidence against the *persisted* Attempt, so evidence built from the
        # in-memory copy is rejected — on PostgreSQL only, which is exactly the
        # kind of backend-shaped difference an in-memory-only test never sees.
        persisted = await self._store.get_attempt(attempt.attempt_id)
        if persisted is None:  # pragma: no cover - the store just wrote it
            raise RunIntegrityError(
                f"Attempt {attempt.attempt_id!r} vanished between execution and acceptance"
            )
        result = _as_conductor_output(persisted.result)
        await self._service.accept_outcome(
            AcceptedNodeOutcome(
                node_run_id=node_run.node_run_id,
                attempt_result=AttemptResult.from_attempt(persisted),
                logical_status=RunStatus.COMPLETED if result.success else RunStatus.FAILED,
                result={"files_changed": result.code.files_changed if result.code else []}
                if result.success
                else None,
                error=None if result.success else result.final_answer,
            )
        )
        return result

    async def _fail_parked(self, run_id: str) -> None:
        """Terminalize a Run and NodeRuns the reconciler parked after a failure.

        `RUN_TRANSITIONS` has no `WAITING -> FAILED` edge: parked work is
        expected to be retried, paused, cancelled or timed out, and a domain
        that has decided to give up has to re-enter `RUNNING` to say so. That is
        not an invention here — `graph/durable_runs/executor.py::_running_run`
        does exactly this before `_mark_failed`, and following the existing
        precedent is better than widening a canonical lifecycle table for one
        caller.

        The Run is left in `RUNNING`, not failed: the caller's next act is to
        report the receipt FAILED, which transitions the Run with the error
        message it actually has. Failing it here would win that race and leave
        the Run's `error` empty.
        """
        for node_run in await self._store.list_node_runs(run_id):
            await self._terminalize_node_run(node_run)
        run = await self._store.get_run(run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return
        if run.status is RunStatus.WAITING:
            await self._store.transition_run(run_id, RunStatus.RUNNING)

    async def _terminalize_node_run(self, node_run: NodeRun) -> None:
        if node_run.status in TERMINAL_RUN_STATUSES:
            return
        if node_run.status is RunStatus.WAITING:
            node_run = await self._store.transition_node_run(
                node_run.node_run_id, RunStatus.RUNNING
            )
        if node_run.status is RunStatus.RUNNING:
            await self._store.transition_node_run(
                node_run.node_run_id, RunStatus.FAILED, error=node_run.error
            )

    async def cancel_attempt(self, attempt_id: str) -> bool:
        """Request cancellation through canonical physical identity."""
        return await self._service.cancel_attempt(attempt_id)


__all__ = ["TASK_EXECUTOR_ID", "TaskAttemptRunner", "TaskWorkItem"]
