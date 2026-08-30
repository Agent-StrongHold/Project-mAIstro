"""Executing admitted Runs that no caller is waiting to drive (#251/#544).

A task Run has a runner holding its receipt and a chat Run executes inline in
the turn that admitted it. A schedule Run has neither: its admission is its
submission, so the canonical consumer owns the physical claim and execution.

The claim is durable evidence, not a bare status. ``ConsumerClaimStore`` writes
Run RUNNING + NodeRun RUNNING + a leased CREATED Attempt atomically. The Attempt
is then executed through the same canonical Attempt service as every other
producer. A dead consumer therefore stops renewing a lease the existing recovery
tick already understands, and a concurrent consumer loses the Run-row claim
before it can create a second physical execution.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from maistro.graph.nodes.base import HUMAN_PAUSE_REASONS
from maistro.runs.consumer_claim import ConsumerClaimStore
from maistro.runs.execution import AttemptExecutionService, ExecutionYielded
from maistro.runs.model import Run, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_INPUTS_KEY, SCHEDULE_SOURCE
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

if TYPE_CHECKING:  # pragma: no cover - typing only; runtime import would cycle
    from collections.abc import Callable

    from maistro.graph.definitions import Node as GraphNode

    NodeResolver = Callable[[str, Any], Any]


SCHEDULE_EXECUTOR_ID = "schedule-consumer"

#: Schedule consumption is an unattended distributed worker, so unlike direct
#: in-process task execution it cannot be leaseless. Thirty seconds gives the
#: heartbeat two missed renewal opportunities (cadence is TTL / 3) before work
#: is considered abandoned, while keeping recovery bounded after process loss.
DEFAULT_SCHEDULE_LEASE_TTL = timedelta(seconds=30)

CONSUMABLE_SOURCES = frozenset({SCHEDULE_SOURCE})


class ScheduleExecutionFailed(RuntimeError):
    """The scheduled node reported failure; the Attempt has recorded it."""


class ScheduleAttemptExecutor:
    """Execute one already-admitted single-node Run through a leased claim."""

    def __init__(
        self,
        run_store: RunStore,
        *,
        runtime: ExecutionRuntime | None = None,
        timeout_s: float | None = None,
        node_resolver: NodeResolver | None = None,
        lease_ttl: timedelta = DEFAULT_SCHEDULE_LEASE_TTL,
    ) -> None:
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        if not callable(getattr(run_store, "claim_consumer_run", None)):
            raise RunIntegrityError(
                "schedule consumption requires a consumer claim capability so RUNNING is "
                "backed by recoverable physical evidence"
            )
        resolved_runtime = runtime or PythonExecutionRuntime()
        self._runs = run_store
        self._claims = cast(ConsumerClaimStore, run_store)
        self._attempts = AttemptExecutionService(
            store=run_store,
            runtime=resolved_runtime,
            lease_ttl=lease_ttl,
        )
        self._runtime_id = type(resolved_runtime).__name__
        self._lease_ttl = lease_ttl
        self._timeout_s = timeout_s
        self._resolver = node_resolver

    async def execute(self, run: Run) -> Run:
        """Atomically claim and execute this Run.

        Claim loss is intentionally not swallowed here: the Container tick must
        distinguish "another consumer owns it" from "our claimed node failed".
        A node-reported failure is physical evidence and reconciles to WAITING;
        it is therefore suppressed after the Attempt records it.
        """
        spec = self._single_node(run)
        inputs = self._inputs(run, spec)
        ctx = self._context(run, spec)
        deadline_at = (
            datetime.now(UTC) + timedelta(seconds=self._timeout_s)
            if self._timeout_s is not None
            else None
        )

        claim = await self._claims.claim_consumer_run(
            run.run_id,
            node_id=spec.node_id,
            runtime_id=self._runtime_id,
            executor_id=SCHEDULE_EXECUTOR_ID,
            lease_ttl=self._lease_ttl,
            deadline_at=deadline_at,
        )

        async def _run(_work_item: Any, context: Any) -> Any:
            # Resolve inside the physical Attempt. Constructor/wiring failure is
            # therefore recorded as FAILED evidence and reconciles through the
            # same canonical path as any other executor failure.
            node = self._resolve(run, spec)
            result = await node.run(inputs, context)
            if result.status == "paused" and result.success:
                raise ExecutionYielded(
                    awaits_human=_awaits_human_answer(result),
                    evidence=_pause_evidence(result),
                )
            if result.status != "completed" or not result.success:
                message = result.error_message or f"node {spec.node_id!r} did not complete"
                raise ScheduleExecutionFailed(f"{result.error_code or result.status}: {message}")
            output = result.output
            if hasattr(output, "model_dump"):
                return output.model_dump(mode="json")
            return output

        with contextlib.suppress(ScheduleExecutionFailed):
            await self._attempts.execute_claimed(
                claim.attempt,
                inputs,
                ctx,
                executor=_run,
                timeout_s=self._timeout_s,
                context_factory=_with_attempt_identity,
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
                "executes single-node Runs — traversal belongs to the durable Graph path"
            )
        return nodes[0]

    def _resolve(self, run: Run, spec: GraphNode) -> Any:
        if self._resolver is not None:
            return self._resolver(spec.node_id, run.graph.materialize())

        from maistro.graph.nodes import get_node

        return get_node(spec.node_type)()

    def _inputs(self, run: Run, spec: GraphNode) -> dict[str, Any]:
        configured = run.provenance.get(SCHEDULE_INPUTS_KEY)
        overrides = dict(configured) if isinstance(configured, dict) else {}
        return {**dict(spec.parameters), **dict(spec.inputs), **overrides}

    def _context(self, run: Run, spec: GraphNode) -> Any:
        from maistro.graph.nodes.base import NodeContext

        return NodeContext(
            run_id=run.run_id,
            dag_id=run.graph.graph_id,
            node_id=spec.node_id,
            user_id=run.actor_principal_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            metadata={},
        )


def _awaits_human_answer(result: Any) -> bool:
    return str((result.metadata or {}).get("paused_reason") or "") in HUMAN_PAUSE_REASONS


def _pause_evidence(result: Any) -> dict[str, Any]:
    return {
        "paused_reason": str((result.metadata or {}).get("paused_reason") or "") or None,
        "resume_at": result.resume_at.isoformat() if result.resume_at else None,
        "metadata": dict(result.metadata or {}),
    }


def _with_attempt_identity(attempt: Any, context: Any) -> Any:
    if not hasattr(context, "model_copy"):
        return context
    return context.model_copy(
        update={"node_run_id": attempt.node_run_id, "attempt_id": attempt.attempt_id}
    )


UNRESOLVABLE_NODE_KIND = "unresolvable_node_kind"


def consumer_owns(run: Run) -> bool:
    return (
        run.status is RunStatus.QUEUED
        and run.provenance.get(ADMISSION_SOURCE) in CONSUMABLE_SOURCES
    )


def unresolvable_reason(run: Run) -> str | None:
    from maistro.graph.nodes import list_kinds

    nodes = run.graph.materialize().nodes
    if len(nodes) != 1:
        return None
    kind = nodes[0].node_type
    if kind not in set(list_kinds()):
        return f"{UNRESOLVABLE_NODE_KIND}: {kind}"
    return None


def executable_by_consumer(run: Run) -> bool:
    if not consumer_owns(run):
        return False
    nodes = run.graph.materialize().nodes
    return len(nodes) == 1 and unresolvable_reason(run) is None


__all__ = [
    "CONSUMABLE_SOURCES",
    "DEFAULT_SCHEDULE_LEASE_TTL",
    "SCHEDULE_EXECUTOR_ID",
    "UNRESOLVABLE_NODE_KIND",
    "ScheduleAttemptExecutor",
    "ScheduleExecutionFailed",
    "consumer_owns",
    "executable_by_consumer",
    "unresolvable_reason",
]
