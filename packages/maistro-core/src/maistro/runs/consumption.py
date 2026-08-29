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

from maistro.runs.execution import ExecutionYielded
from maistro.runs.model import Run, RunStatus
from maistro.runs.service import RunExecutionService
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_INPUTS_KEY, SCHEDULE_SOURCE
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

if TYPE_CHECKING:  # pragma: no cover - typing only; runtime import would cycle
    from collections.abc import Callable

    from maistro.graph.definitions import Node as GraphNode

    #: `build_node_resolver`'s shape: (node_id, graph) -> a constructed node.
    #: Type-checking only: `from __future__ import annotations` makes the
    #: annotation lazy, and importing `Callable` at runtime here buys nothing.
    NodeResolver = Callable[[str, Any], Any]

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
        node_resolver: NodeResolver | None = None,
    ) -> None:
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        self._runs = run_store
        self._service = RunExecutionService(
            store=run_store,
            runtime=runtime or PythonExecutionRuntime(),
        )
        self._timeout_s = timeout_s
        #: The Container's `build_node_resolver`, which is where
        #: `agent.spawn_harness` gets its adapters, `agent.delegate_remote` its
        #: delegator/guest peers/RunStore, and `rsi.quota_pace_trigger` the real
        #: usage log. Constructing bare from the registry leaves those None:
        #: the kinds pass eligibility, because they *are* registered, and then
        #: fail or compute against empty state inside a Run that looks properly
        #: admitted -- the shape #147 already had to find once.
        self._resolver = node_resolver

    async def execute(self, run: Run) -> Run:
        """Execute the Run's single node, leaving a NodeRun and an Attempt.

        Returns the Run as the store sees it afterwards: `COMPLETED` when the
        node succeeded (derived from the NodeRun, not asserted here), parked
        `WAITING` when the physical try failed — the recovery disposition's
        parked row, awaiting a retry decision rather than silently retried.
        """
        spec = self._single_node(run)
        node = self._resolve(run, spec)
        inputs = self._inputs(run, spec)
        ctx = self._context(run, spec)

        async def _run(_work_item: Any, context: Any) -> Any:
            # The runtime-provided context, not the one built above: only this
            # one carries the canonical Attempt identity, and the factory has
            # already run by the time the executor is called.
            result = await node.run(inputs, context)
            if result.status == "paused" and result.success:
                # A wait or HITL node that paused has not failed. Recorded as
                # one, the Attempt said the node broke, the Run parked WAITING,
                # and `resume_at` plus the prompt were discarded -- so a
                # scheduled `human.*` node could never reach PAUSED or show what
                # it was waiting for.
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

        # A failure is recorded on the Attempt and the reconciler has parked
        # the NodeRun and the Run. Parked is the disposition — re-raising
        # would make the tick's caller invent a second one.
        with contextlib.suppress(ScheduleExecutionFailed):
            await self._service.execute_node(
                run.run_id,
                spec.node_id,
                inputs,
                ctx,
                executor=_run,
                executor_id=SCHEDULE_EXECUTOR_ID,
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
                "executes single-node Runs — traversal belongs to the durable "
                "Graph path"
            )
        return nodes[0]

    def _resolve(self, run: Run, spec: GraphNode) -> Any:
        """The node as the wired resolver builds it, falling back to the registry.

        The fallback keeps a consumer constructed without a resolver working for
        the plain kinds, which is every kind the resolver does not special-case.
        It is not a silent downgrade for the injected ones: those are exactly
        the kinds that read as a returned failure rather than an error.
        """
        if self._resolver is not None:
            return self._resolver(spec.node_id, run.graph.materialize())

        from maistro.graph.nodes import get_node

        return get_node(spec.node_type)()

    def _inputs(self, run: Run, spec: GraphNode) -> dict[str, Any]:
        """The node's static configuration, overridden by the schedule's payload.

        `parameters` first, exactly as the durable graph executor composes its
        `static_inputs`. Direct-work admission stores a node's configuration
        there, so dropping it made a scheduled template lose required fields --
        the node then failed validation, or ran on defaults, over a template
        that had configured it the canonical way.
        """
        configured = run.provenance.get(SCHEDULE_INPUTS_KEY)
        overrides = dict(configured) if isinstance(configured, dict) else {}
        return {**dict(spec.parameters), **dict(spec.inputs), **overrides}

    def _context(self, run: Run, spec: GraphNode) -> Any:
        """The node context, minus the identities that do not exist yet.

        `node_run_id` and `attempt_id` are deliberately absent here: this runs
        before the NodeRun and Attempt are created, so any value put in them
        would be a fiction. `_with_attempt_identity` fills them in once the
        Attempt is persisted.
        """
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


#: Pause reasons that mean a person, not the system, is the one owed an action.
#: The same two the durable graph executor treats as a human pause, so a HITL
#: node reaching PAUSED does not depend on which path executed it.
_HUMAN_PAUSE_REASONS = frozenset({"awaiting_human_answer", "awaiting_human_approval"})


def _awaits_human_answer(result: Any) -> bool:
    return str((result.metadata or {}).get("paused_reason") or "") in _HUMAN_PAUSE_REASONS


def _pause_evidence(result: Any) -> dict[str, Any]:
    """What the pause was for, kept on the Attempt where a reader can find it."""
    return {
        "paused_reason": str((result.metadata or {}).get("paused_reason") or "") or None,
        "resume_at": result.resume_at.isoformat() if result.resume_at else None,
        "metadata": dict(result.metadata or {}),
    }


def _with_attempt_identity(attempt: Any, context: Any) -> Any:
    """Stamp the canonical Attempt identity onto the node's context.

    Runs after the Attempt is persisted and marked running, which is the only
    moment both ids exist. Without it a node that files correlated work -- a
    delegation filing its child Run -- records no `parent_node_run_id`, and an
    audit integration cannot attribute activity to the physical try that
    produced it. The durable graph executor has had this seam all along; the
    consumer built its context up front and then ignored the runtime's.
    """
    if not hasattr(context, "model_copy"):
        return context
    return context.model_copy(
        update={"node_run_id": attempt.node_run_id, "attempt_id": attempt.attempt_id}
    )


#: Error recorded on a Run the consumer owns and can never run.
UNRESOLVABLE_NODE_KIND = "unresolvable_node_kind"


def consumer_owns(run: Run) -> bool:
    """Whether this Run is the consumer's to dispose of at all.

    QUEUED plus an allowlisted admission source. CREATED is never owned — it
    is a legitimate resting state for Runs that must not execute here
    (delegation projections, unvetted ids), and a source outside the
    allowlist belongs to whoever admitted it.
    """
    return (
        run.status is RunStatus.QUEUED
        and run.provenance.get(ADMISSION_SOURCE) in CONSUMABLE_SOURCES
    )


def unresolvable_reason(run: Run) -> str | None:
    """Why an owned Run can never execute here, or None when it merely waits.

    The distinction is "never" against "not yet", and it decides whether
    leaving the Run QUEUED is honest. A multi-node Run is owed to the durable
    Graph traversal (#44/#34): it stays QUEUED because something will
    eventually run it. A single node whose kind this process cannot resolve is
    owed to nobody — no later tick makes an unregistered kind appear — so
    leaving it QUEUED is the "admitted work nobody executes" state #251 exists
    to remove, reproduced one level in.
    """
    from maistro.graph.nodes import list_kinds

    nodes = run.graph.materialize().nodes
    if len(nodes) != 1:
        return None
    kind = nodes[0].node_type
    if kind not in set(list_kinds()):
        return f"{UNRESOLVABLE_NODE_KIND}: {kind}"
    return None


def executable_by_consumer(run: Run) -> bool:
    """Whether the consumer tick can actually execute this Run.

    Owned, single-node, and naming a kind this process can resolve.
    """
    if not consumer_owns(run):
        return False
    nodes = run.graph.materialize().nodes
    return len(nodes) == 1 and unresolvable_reason(run) is None


__all__ = [
    "CONSUMABLE_SOURCES",
    "SCHEDULE_EXECUTOR_ID",
    "UNRESOLVABLE_NODE_KIND",
    "ScheduleAttemptExecutor",
    "ScheduleExecutionFailed",
    "consumer_owns",
    "executable_by_consumer",
    "unresolvable_reason",
]
