"""Executing admitted Runs that no caller is waiting to drive (#251).

A task Run has a runner holding its receipt and a chat Run executes inline in
the turn that admitted it. A schedule Run has neither: its admission *is* its
submission, and until now nothing ever executed what `ScheduleRunAdmitter`
admitted — canonical Runs sat `QUEUED` forever, which is the exact
"admitted work nobody executes" state #251 exists to remove.

This module is the canonical consumer's execution half, shaped deliberately
after `TaskAttemptExecutor` and `ChatAttemptExecutor`: one entry point onto
the same `RunExecutionService` spine, so a third producer does not grow a
third idea of how to use it. The claim half lives on the Container tick
(`execute_admitted_runs`), which finds QUEUED work via
`RunStore.list_by_status` and claims each Run with the QUEUED→RUNNING
lifecycle transition — the transition table itself is the mutex, so two
concurrent ticks cannot both execute one Run.

Scope is deliberate: **single-node Runs from allowlisted admission sources.**
`CREATED` is a legitimate resting state (a delegation child is a projection
that must never execute here — ADR-082426-6201 — and an unvetted run_id must
stay untouched), so eligibility is `QUEUED` plus an explicit source
allowlist, never "anything non-terminal". Multi-node Runs need Graph
traversal, which is the durable-graph convergence (#44/#34); they stay QUEUED
and visible rather than being half-executed here.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from maistro.runs.model import Run, RunStatus
from maistro.runs.service import RunExecutionService
from maistro.runs.sources import SCHEDULE_INPUTS_KEY, SCHEDULE_SOURCE
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

if TYPE_CHECKING:  # pragma: no cover - typing only; runtime import would cycle
    from maistro.graph.definitions import Node as GraphNode

#: `executor_id` recorded on every Attempt the consumer drives, the way
#: `TASK_EXECUTOR_ID` names the task runner and `CHAT_EXECUTOR_ID` the
#: Conduit. It answers "what kind of work was this" on the physical record.
SCHEDULE_EXECUTOR_ID = "schedule-consumer"

#: Admission sources the consumer may execute. An allowlist rather than
#: "everything QUEUED": a source joins by deciding to, in one reviewed place,
#: never by having its Runs picked up as a side effect of being non-terminal.
CONSUMABLE_SOURCES = frozenset({SCHEDULE_SOURCE})


class ScheduleExecutionFailed(RuntimeError):
    """The scheduled node reported failure; the Attempt has recorded it."""


class ScheduleAttemptExecutor:
    """Run one admitted single-node Run as an Attempt under its NodeRun.

    Holds no per-Run state: everything is read back from the store, so two
    consumer processes and a restarted one all reach the same answer. The Run
    terminalizes from its NodeRun through the canonical derivation
    (ADR-082526-237d) — this executor performs no second, domain-specific
    terminalization call.
    """

    def __init__(
        self,
        run_store: RunStore,
        *,
        runtime: ExecutionRuntime | None = None,
        timeout_s: float | None = None,
    ) -> None:
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        self._runs = run_store
        self._service = RunExecutionService(
            store=run_store,
            runtime=runtime or PythonExecutionRuntime(),
        )
        self._timeout_s = timeout_s

    async def execute(self, run: Run) -> Run:
        """Execute the Run's single node, leaving a NodeRun and an Attempt.

        Returns the Run as the store sees it afterwards: `COMPLETED` when the
        node succeeded (derived from the NodeRun, not asserted here), parked
        `WAITING` when the physical try failed — the recovery disposition's
        parked row, awaiting a retry decision rather than silently retried.
        """
        spec = self._single_node(run)
        node = self._resolve(spec)
        inputs = self._inputs(run, spec)
        ctx = self._context(run, spec)

        async def _run(_work_item: Any, _context: Any) -> Any:
            result = await node.run(inputs, ctx)
            if result.status != "completed" or not result.success:
                message = result.error_message or f"node {spec.node_id!r} did not complete"
                raise ScheduleExecutionFailed(f"{result.error_code or result.status}: {message}")
            output = result.output
            if hasattr(output, "model_dump"):
                return output.model_dump(mode="json")
            return output

        # A failure is recorded on the Attempt and the reconciler has parked
        # the NodeRun and the Run. Parked is the disposition — re-raising
        # would make the tick's caller invent a second one.
        with contextlib.suppress(ScheduleExecutionFailed):
            await self._service.execute_node(
                run.run_id,
                spec.node_id,
                inputs,
                {"run_id": run.run_id, "node_id": spec.node_id},
                executor=_run,
                executor_id=SCHEDULE_EXECUTOR_ID,
                timeout_s=self._timeout_s,
            )
        settled = await self._runs.get_run(run.run_id)
        if settled is None:
            raise RunIntegrityError(f"Run {run.run_id!r} disappeared during consumption")
        return settled

    def _single_node(self, run: Run) -> GraphNode:
        nodes = run.graph.materialize().nodes
        if len(nodes) != 1:
            raise RunIntegrityError(
                f"Run {run.run_id!r} has {len(nodes)} Graph nodes; the consumer "
                "executes single-node Runs — traversal belongs to the durable "
                "Graph path"
            )
        return nodes[0]

    def _resolve(self, spec: GraphNode) -> Any:
        from maistro.graph.nodes import get_node

        return get_node(spec.node_type)()

    def _inputs(self, run: Run, spec: GraphNode) -> dict[str, Any]:
        """The template's node inputs, overridden by the schedule's payload."""
        configured = run.provenance.get(SCHEDULE_INPUTS_KEY)
        overrides = dict(configured) if isinstance(configured, dict) else {}
        return {**dict(spec.inputs), **overrides}

    def _context(self, run: Run, spec: GraphNode) -> Any:
        from maistro.graph.nodes.base import NodeContext

        return NodeContext(
            run_id=run.run_id,
            dag_id=run.graph.graph_id,
            node_id=spec.node_id,
            user_id=run.actor_principal_id,
            project_id=run.project_id,
            metadata={},
        )


def executable_by_consumer(run: Run) -> bool:
    """Whether the consumer tick may claim this Run.

    QUEUED plus an allowlisted source plus a single registered node. CREATED
    is never eligible — it is a legitimate resting state for Runs that must
    not execute here (delegation projections, unvetted ids).
    """
    from maistro.graph.nodes import list_kinds

    if run.status is not RunStatus.QUEUED:
        return False
    if run.provenance.get("admission_source") not in CONSUMABLE_SOURCES:
        return False
    nodes = run.graph.materialize().nodes
    if len(nodes) != 1:
        return False
    return nodes[0].node_type in set(list_kinds())


__all__ = [
    "CONSUMABLE_SOURCES",
    "SCHEDULE_EXECUTOR_ID",
    "ScheduleAttemptExecutor",
    "ScheduleExecutionFailed",
    "executable_by_consumer",
]
