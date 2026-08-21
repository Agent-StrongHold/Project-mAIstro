"""Canonical domain entry point for creating Runs and executing individual Nodes."""

from __future__ import annotations

from typing import Any

from maistro.graph.definitions import Graph
from maistro.runs.execution import AttemptExecutionService, AttemptReconciler
from maistro.runs.model import Attempt, NodeRun, Run
from maistro.runs.store import RunStore
from maistro.runtime import ExecutionCallable, ExecutionRuntime


class RunExecutionService:
    """Drive the universal execution spine without owning graph semantics.

    This is the stable handoff surface for graph traversal, schedulers, product
    adapters, and capability execution. It creates canonical logical identity
    and delegates one physical try to :class:`AttemptExecutionService`.

    It deliberately does not decide graph readiness/traversal, retry policy,
    authorization, provider selection, scheduling, or Run completion.
    """

    def __init__(
        self,
        *,
        store: RunStore,
        runtime: ExecutionRuntime,
        reconciler: AttemptReconciler | None = None,
    ) -> None:
        self._store = store
        self._attempts = AttemptExecutionService(
            store=store,
            runtime=runtime,
            reconciler=reconciler,
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
    ) -> tuple[NodeRun, Attempt]:
        """Create a logical NodeRun and execute its first physical Attempt."""

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
    ) -> Attempt:
        """Execute a new physical Attempt under an existing logical NodeRun."""

        return await self._attempts.execute(
            node_run_id,
            work_item,
            execution_context,
            executor=executor,
            executor_id=executor_id,
            runtime_id=runtime_id,
            timeout_s=timeout_s,
            resume_checkpoint_id=resume_checkpoint_id,
        )

    async def cancel_attempt(self, attempt_id: str) -> bool:
        """Request cancellation using canonical physical Attempt identity."""

        return await self._attempts.cancel(attempt_id)


__all__ = ["RunExecutionService"]
