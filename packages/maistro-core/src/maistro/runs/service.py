"""Canonical domain entry point for creating Runs and executing individual Nodes."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from maistro.graph.definitions import Graph
from maistro.observability.correlation import bind_execution_context
from maistro.runs.execution import (
    AttemptContextFactory,
    AttemptExecutionService,
    AttemptReconciler,
)
from maistro.runs.model import AcceptedNodeOutcome, Attempt, NodeRun, Run
from maistro.runs.store import RunStore
from maistro.runtime import ExecutionCallable, ExecutionRuntime


class RunExecutionService:
    """Drive the universal execution spine without owning graph semantics.

    This is the stable handoff surface for graph traversal, schedulers, product
    adapters, and capability execution. It creates canonical logical identity
    and delegates one physical try to :class:`AttemptExecutionService`.

    It deliberately does not decide graph readiness/traversal, retry policy,
    authorization, provider selection, scheduling, or product-specific logical
    outcomes. Ordinary successful Attempts reconcile automatically; richer
    domains may defer that successful reconciliation and accept one explicit
    logical projection after the physical evidence is durable.
    """

    def __init__(
        self,
        *,
        store: RunStore,
        runtime: ExecutionRuntime,
        reconciler: AttemptReconciler | None = None,
        lease_ttl: timedelta | None = None,
    ) -> None:
        """``lease_ttl`` opts this service's Attempts into crash recovery.

        Passed straight down to `AttemptExecutionService`, which holds the
        heartbeat (ADR-082526-b36a). Present here because this is the seam a
        domain constructs — without it a deployment has no way to opt in, and
        the recovery mechanism is reachable only in tests.
        """
        self._store = store
        self._attempts = AttemptExecutionService(
            store=store,
            runtime=runtime,
            reconciler=reconciler,
            lease_ttl=lease_ttl,
        )

    async def create_run(
        self,
        graph: Graph,
        *,
        parent_run_id: str | None = None,
        parent_node_run_id: str | None = None,
        allow_cross_project: bool = False,
        persona_id: str | None = None,
        actor_principal_id: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> Run:
        """Create one canonical logical Run from an immutable Graph snapshot."""

        return await self._store.create_run(
            graph,
            parent_run_id=parent_run_id,
            parent_node_run_id=parent_node_run_id,
            allow_cross_project=allow_cross_project,
            persona_id=persona_id,
            actor_principal_id=actor_principal_id,
            provenance=provenance,
        )

    async def execute_node(
        self,
        run_id: str,
        node_id: str,
        work_item: Any,
        execution_context: Any,
        *,
        executor: ExecutionCallable,
        executor_id: str = "",
        runtime_id: str | None = None,
        timeout_s: float | None = None,
        resume_checkpoint_id: str | None = None,
        reconcile_logical: bool = True,
        context_factory: AttemptContextFactory | None = None,
    ) -> tuple[NodeRun, Attempt]:
        """Create a logical NodeRun and execute its first physical Attempt.

        ``context_factory`` is forwarded to the Attempt execution, which runs it
        once the Attempt is persisted. A caller that builds its execution
        context *before* this call cannot name the `node_run_id` or `attempt_id`
        it is about to be given -- both are still empty -- so work the node files
        loses its ancestry and audit cannot attribute it to a physical Attempt.

        The Run is bound onto the ambient correlation context around the whole
        call, so the NodeRun and Attempt ids the layer below adds join to it
        rather than standing alone. It comes from the argument and costs no
        store read; `workspace_id` and `project_id` are left to whichever seam
        already holds them, because reading the Run back here to recover two
        fields would put a query on every node execution to decorate a log
        line (#707).
        """

        with bind_execution_context(run_id=run_id):
            node_run = await self._store.create_node_run(run_id, node_id=node_id)
            attempt = await self._attempts.execute(
                node_run.node_run_id,
                work_item,
                execution_context,
                executor=executor,
                executor_id=executor_id,
                runtime_id=runtime_id,
                timeout_s=timeout_s,
                resume_checkpoint_id=resume_checkpoint_id,
                reconcile_logical=reconcile_logical,
                context_factory=context_factory,
            )
            reconciled = await self._store.get_node_run(node_run.node_run_id)
            if reconciled is None:
                raise RuntimeError("canonical NodeRun disappeared during execution")
            return reconciled, attempt

    async def retry_node(
        self,
        node_run_id: str,
        work_item: Any,
        execution_context: Any,
        *,
        executor: ExecutionCallable,
        executor_id: str = "",
        runtime_id: str | None = None,
        timeout_s: float | None = None,
        resume_checkpoint_id: str | None = None,
        reconcile_logical: bool = True,
        context_factory: AttemptContextFactory | None = None,
    ) -> Attempt:
        """Execute a new physical Attempt under an existing logical NodeRun.

        ``context_factory`` is forwarded for the same reason `execute_node`
        forwards it: a caller that builds its context before the call cannot
        name the `attempt_id` it is about to be given. A retry needed it as
        much as a first try -- work the node files on the second Attempt was
        losing its ancestry, and a resume is a retry (#641).

        A retry arrives holding only the NodeRun, so the Run is resolved from
        it -- the one store read correlation costs here, and the only way to
        get the id. Without it a retry's logs and events named a NodeRun and no
        Run while the first try named both, so the two tries at the same work
        could not be put side by side, which is the one question a retry raises.

        A NodeRun the store cannot find binds nothing rather than raising:
        `execute` below is about to fail on the same absence with a better
        error, and correlation must not become the thing that reports it (#707).
        """

        node_run = await self._store.get_node_run(node_run_id)
        with bind_execution_context(run_id=node_run.run_id if node_run else None):
            return await self._attempts.execute(
                node_run_id,
                work_item,
                execution_context,
                executor=executor,
                executor_id=executor_id,
                runtime_id=runtime_id,
                timeout_s=timeout_s,
                resume_checkpoint_id=resume_checkpoint_id,
                reconcile_logical=reconcile_logical,
                context_factory=context_factory,
            )

    async def accept_outcome(self, outcome: AcceptedNodeOutcome) -> NodeRun:
        """Accept a domain projection of already-durable physical Attempt evidence."""

        return await self._attempts.accept_outcome(outcome)

    async def cancel_attempt(self, attempt_id: str) -> bool:
        """Request cancellation using canonical physical Attempt identity."""

        return await self._attempts.cancel(attempt_id)


__all__ = ["RunExecutionService"]
