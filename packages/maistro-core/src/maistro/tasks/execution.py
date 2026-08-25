"""Executing a queued task as a physical Attempt under its Run (#143).

#41 gave every submitted task a canonical Run over a one-node Graph. Execution
did not follow: `TaskRunner` called its injected executor directly, so the Run's
node had no NodeRun, nothing recorded when a physical try started or how long it
took, and `GET /v1/runs/{run_id}/node-runs` was an endpoint that was correct and
always empty. A retry was invisible — the executor was called again, or it was
not, and the Run could not tell you which.

The seam it should have gone through already existed and was fully implemented:
`maistro.runs.service.RunExecutionService.execute_node`. What was missing is the
adapter between two shapes — a `TaskExecutor` takes a `TaskCreate` and returns a
`ConductorOutput`, while Runtime takes an opaque work item plus an execution
context and treats the return value as opaque. That adapter is this module, and
it lives on the tasks side for the same reason `tasks/admission.py` does: the
runs package must not learn the shape of every entry point that feeds it.

Two things the adapter decides, because nothing below it can:

*Failure.* A task executor signals failure by returning `success=False`, not by
raising, so a naive adapter would record every failed task as a *completed*
physical Attempt with a failed Run above it. It raises :class:`TaskExecutionFailed`
instead, carrying the output, so the Attempt is FAILED, the NodeRun is parked,
and the receipt's own failure branch still writes exactly what it wrote before.

*What is persisted.* A `ConductorOutput` carries generated plans, code and
reviews. The Attempt's `result` is durable evidence, not a transcript, so the
adapter persists a small JSON-safe summary and hands the full output back to the
caller in-process.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from maistro.runs.model import TERMINAL_ATTEMPT_STATUSES, NodeRun
from maistro.runs.service import RunExecutionService
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.agents.types import ConductorOutput
    from maistro.tasks.models import TaskCreate
    from maistro.tasks.runner import TaskExecutor

#: `executor_id` recorded on every Attempt the task runner drives.
TASK_EXECUTOR_ID = "task_runner"


class TaskExecutionFailed(Exception):
    """The task executor returned an unsuccessful result.

    Raised rather than returned so the physical Attempt records a failure. The
    output travels on the exception because the receipt's failure branch needs
    `final_answer` verbatim: routing failure through the Attempt must not change
    what a `/tasks` caller reads.
    """

    def __init__(self, output: ConductorOutput) -> None:
        super().__init__(output.final_answer or "task execution failed")
        self.output = output
        # The same JSON-safe summary a successful Attempt keeps. A failed task
        # can still have changed files, and an Attempt that recorded only the
        # error text would drop that evidence exactly where a retry or an audit
        # goes looking for it.
        self.attempt_evidence = attempt_result(output)


def attempt_result(output: ConductorOutput) -> dict[str, Any]:
    """The JSON-safe evidence one task execution leaves on its Attempt.

    Deliberately small. `files_changed` is what the receipt itself keeps, and
    `final_answer` is what a caller reads when the work ends; the plan, the
    generated code and the review stay out of the durable record.
    """
    return {
        "success": output.success,
        "final_answer": output.final_answer,
        "files_changed": list(output.code.files_changed) if output.code else [],
    }


class TaskAttemptExecutor:
    """Run one task's work as an Attempt under its Run's single NodeRun.

    Holds no per-task state: the NodeRun to retry under is read from the store
    each time, so two workers and a restarted process all reach the same answer.
    """

    def __init__(
        self,
        run_store: RunStore,
        *,
        runtime: ExecutionRuntime | None = None,
        timeout_s: float | None = None,
        lease_ttl: timedelta | None = None,
    ) -> None:
        if timeout_s is not None and timeout_s <= 0:
            # Rejected here rather than by `AttemptExecutionService`, which
            # would only see it after the NodeRun exists — leaving a created
            # NodeRun with no Attempt under it, an execution record that is
            # incomplete rather than absent.
            raise ValueError("timeout_s must be > 0")
        self._runs = run_store
        self._service = RunExecutionService(
            store=run_store,
            runtime=runtime or PythonExecutionRuntime(),
            lease_ttl=lease_ttl,
        )
        # Explicitly None by default, for the same reason `timeout_s` is. A TTL
        # is a promise this process will keep renewing, and a deployment that
        # has no sweeper running would be making a promise nobody collects on:
        # every Attempt would carry an expiry that nothing acts upon. Opting in
        # means running `Container.recover_abandoned_attempts` on a timer, which
        # is an operational decision this constructor cannot make
        # (ADR-082526-b36a).
        self._lease_ttl = lease_ttl
        # Explicitly None by default. `TaskCreate` carries no deadline, so there
        # is no per-task number to pass, and inventing a global one here would
        # start timing out long tasks that have always been allowed to run —
        # a behaviour change dressed as plumbing. A deployment that wants one
        # supplies it; giving tasks a real deadline of their own is #43's.
        self._timeout_s = timeout_s

    async def execute(
        self,
        run_id: str,
        request: TaskCreate,
        executor: TaskExecutor,
    ) -> ConductorOutput:
        """Execute one task, returning its output and leaving a NodeRun + Attempt.

        Raises :class:`TaskExecutionFailed` when the executor reports failure,
        after the Attempt has been recorded as failed.
        """
        node_id = await self._node_id(run_id)
        existing = await self._node_run_for(run_id, node_id)
        captured: list[ConductorOutput] = []

        async def _run(work_item: Any, _context: Any) -> dict[str, Any]:
            output = await executor(work_item)
            if not output.success:
                raise TaskExecutionFailed(output)
            captured.append(output)
            return attempt_result(output)

        context = {"run_id": run_id, "node_id": node_id}
        if existing is None:
            await self._service.execute_node(
                run_id,
                node_id,
                request,
                context,
                executor=_run,
                executor_id=TASK_EXECUTOR_ID,
                timeout_s=self._timeout_s,
            )
        else:
            # A second execution of the same task is a second Attempt under the
            # same logical NodeRun, not a second NodeRun. Creating another
            # NodeRun would say the Run grew a node, which is false: the Graph
            # has one, and it was tried twice.
            await self._service.retry_node(
                existing.node_run_id,
                request,
                context,
                executor=_run,
                executor_id=TASK_EXECUTOR_ID,
                timeout_s=self._timeout_s,
            )
        if not captured:  # pragma: no cover - unreachable: _run always fills it
            raise RunIntegrityError("task Attempt completed without capturing its output")
        return captured[0]

    async def cancel(self, run_id: str) -> bool:
        """Cancel a task's in-flight Attempt by canonical physical identity.

        Returns False when there is nothing in flight — no NodeRun yet, or its
        latest Attempt already terminal. Cancelling the *Run* is a separate and
        equally real act: it stops the work from being picked up at all, which
        is what `TaskQueue.cancel` and the runner's refusal already do. This is
        the other half, for work that is already running somewhere.
        """
        node_id = await self._node_id(run_id)
        node_run = await self._node_run_for(run_id, node_id)
        if node_run is None:
            return False
        attempts = await self._runs.list_attempts(node_run.node_run_id)
        in_flight = next(
            (a for a in reversed(attempts) if a.status not in TERMINAL_ATTEMPT_STATUSES),
            None,
        )
        if in_flight is None:
            return False
        return await self._service.cancel_attempt(in_flight.attempt_id)

    async def _node_id(self, run_id: str) -> str:
        run = await self._runs.get_run(run_id)
        if run is None:
            raise RunIntegrityError(f"Run {run_id!r} does not exist")
        nodes = run.graph.materialize().nodes
        if len(nodes) != 1:
            raise RunIntegrityError(
                f"task Run {run_id!r} has {len(nodes)} Graph nodes; direct work admits exactly one"
            )
        return nodes[0].node_id

    async def _node_run_for(self, run_id: str, node_id: str) -> NodeRun | None:
        node_runs = [nr for nr in await self._runs.list_node_runs(run_id) if nr.node_id == node_id]
        return node_runs[-1] if node_runs else None


__all__ = [
    "TASK_EXECUTOR_ID",
    "TaskAttemptExecutor",
    "TaskExecutionFailed",
    "attempt_result",
]
