"""Canvas adapter onto the canonical Run -> NodeRun -> Attempt spine (#735).

Canvas owns generation receipts, assets, layer state, queue claims and retry
policy. It does not own a second execution history. This adapter binds Canvas to
one already-authorized Workspace/Project and records physical provider work in
the public canonical RunStore without teaching core anything about Canvas.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from maistro.graph.definitions import Edge, Graph, Node
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    Attempt,
    AttemptStatus,
    CancellationCause,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.service import RunExecutionService
from maistro.runs.sources import ADMISSION_SOURCE
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

_CANONICAL_RUN_PARAM = "canonical_run_id"
_CANVAS_SOURCE = "canvas_generation"
_CANVAS_EXECUTOR_ID = "canvas_job_runner"

T = TypeVar("T")


def canonical_run_id(params: dict[str, object]) -> str | None:
    """Return the canonical Run correlated into a Canvas job's JSON params."""

    value = params.get(_CANONICAL_RUN_PARAM)
    return value if isinstance(value, str) and value else None


def correlate_run(params: dict[str, object], run_id: str) -> None:
    """Persist a Run correlation in the job's already-durable JSON payload."""

    params[_CANONICAL_RUN_PARAM] = run_id


def _stages(action: str) -> tuple[str, ...]:
    if action == "reference":
        return (
            "reference.hero",
            "reference.side",
            "reference.back",
            "reference.three-quarter",
        )
    return (action,)


def _node_id(job_id: str, stage: str) -> str:
    return f"canvas:{job_id}:{stage}"


class CanvasCanonicalExecution:
    """Record Canvas physical execution in one bound canonical scope.

    The Workspace/Project are constructor bindings supplied by the caller after
    authorization. Canvas never derives either from ``org_id``, a canvas id, a
    layer id, or a standalone placeholder.
    """

    def __init__(
        self,
        run_store: RunStore,
        *,
        workspace_id: str,
        project_id: str,
        runtime: ExecutionRuntime | None = None,
    ) -> None:
        if not workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        if not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        self._runs = run_store
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._service = RunExecutionService(
            store=run_store,
            runtime=runtime or PythonExecutionRuntime(),
        )
        # Canvas's own worker lease is deliberately separate from the canonical
        # Attempt lease. If that worker disappears, the adapter must still fence
        # the physical Attempt before a replacement try or terminal receipt.
        self._reconciler = AttemptLifecycleReconciler(run_store)

    async def admit(
        self,
        *,
        job_id: str,
        canvas_id: str,
        layer_id: str,
        action: str,
        actor_principal_id: str | None,
    ) -> str:
        """Create exactly one canonical Run for one accepted Canvas job."""

        stages = _stages(action)
        nodes = [
            Node(
                node_id=_node_id(job_id, stage),
                node_type=f"canvas.{stage}",
                name=f"Canvas {stage}",
                parameters={"canvas_id": canvas_id, "layer_id": layer_id},
                metadata={"canvas_stage": stage},
            )
            for stage in stages
        ]
        edges: list[Edge] = []
        if action == "reference":
            hero = _node_id(job_id, "reference.hero")
            edges = [Edge(from_node=hero, to_node=_node_id(job_id, stage)) for stage in stages[1:]]
        graph = Graph(
            graph_id=f"canvas:{job_id}",
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            name=f"Canvas generation {job_id}",
            nodes=nodes,
            edges=edges,
            metadata={"canvas_job_id": job_id},
        )
        run = await self._service.create_run(
            graph,
            actor_principal_id=actor_principal_id,
            provenance={
                ADMISSION_SOURCE: _CANVAS_SOURCE,
                "canvas_job_id": job_id,
                "canvas_id": canvas_id,
                "layer_id": layer_id,
                "canvas_action": action,
            },
        )
        try:
            await self._runs.transition_run(run.run_id, RunStatus.QUEUED)
        except BaseException:
            with contextlib.suppress(Exception):
                await self._runs.transition_run(run.run_id, RunStatus.CANCELLED)
                await self._runs.delete_run(run.run_id)
            raise
        return run.run_id

    async def execute_stage(
        self,
        run_id: str,
        stage: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        """Execute or retry one Canvas stage under one canonical NodeRun.

        A stage that already completed is replayed from durable Attempt evidence,
        not sent to the provider again. A failed previous try is retried under
        the same NodeRun, leaving both Attempts inspectable.
        """

        run = await self._require_run(run_id)
        node_id = self._stage_node_id(run, stage)
        node_run = await self._node_run(run_id, node_id)

        if node_run is not None and node_run.status is RunStatus.COMPLETED:
            attempts = await self._runs.list_attempts(node_run.node_run_id)
            completed = next(
                (
                    attempt
                    for attempt in reversed(attempts)
                    if attempt.status is AttemptStatus.COMPLETED
                ),
                None,
            )
            if completed is None:
                raise RunIntegrityError(
                    f"completed Canvas NodeRun {node_run.node_run_id!r} has no completed Attempt"
                )
            return await self._project_stage_result(run_id, stage, cast(T, completed.result))

        await self._resume_for_execution(run_id)
        captured: list[T] = []

        async def _execute(_work_item: object, _context: object) -> T:
            result = await operation()
            captured.append(result)
            return result

        context = {"run_id": run_id, "node_id": node_id, "canvas_stage": stage}
        if node_run is None:
            _node_run_record, attempt = await self._service.execute_node(
                run_id,
                node_id,
                None,
                context,
                executor=_execute,
                executor_id=_CANVAS_EXECUTOR_ID,
            )
        else:
            attempts = await self._runs.list_attempts(node_run.node_run_id)
            active = next(
                (
                    item
                    for item in reversed(attempts)
                    if item.status not in TERMINAL_ATTEMPT_STATUSES
                ),
                None,
            )
            if active is not None:
                # The Canvas lease was reclaimed but the physical Attempt can
                # still say RUNNING after a dead worker. Settle/fence it first;
                # then re-enter from persisted truth. If the old worker actually
                # completed in the race, the recursive read returns that result
                # instead of issuing a duplicate provider effect.
                await self._settle_abandoned_attempt(
                    active,
                    error="Canvas worker lease was reclaimed before retry",
                    cancellation=CancellationCause.RECOVERED,
                )
                return await self.execute_stage(run_id, stage, operation)
            attempt = await self._service.retry_node(
                node_run.node_run_id,
                None,
                context,
                executor=_execute,
                executor_id=_CANVAS_EXECUTOR_ID,
            )
        if captured:
            return await self._project_stage_result(run_id, stage, captured[0])
        if attempt.status is AttemptStatus.COMPLETED:
            return await self._project_stage_result(run_id, stage, cast(T, attempt.result))
        raise RunIntegrityError(
            f"Canvas stage {stage!r} returned without a completed Attempt result"
        )

    async def cancel(self, run_id: str) -> None:
        """Cancel live physical work and terminalize observed logical work."""

        run = await self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return
        for node_run in await self._runs.list_node_runs(run_id):
            attempts = await self._runs.list_attempts(node_run.node_run_id)
            active = next(
                (
                    item
                    for item in reversed(attempts)
                    if item.status not in TERMINAL_ATTEMPT_STATUSES
                ),
                None,
            )
            if active is not None:
                await self._settle_abandoned_attempt(
                    active,
                    error="Canvas generation cancelled",
                    cancellation=CancellationCause.REQUESTED,
                )

        # A failed Attempt is intentionally parked while Canvas still owns a
        # retry decision. User cancellation *is* that decision: don't retry.
        # Terminalize every observed unfinished NodeRun so the canonical logical
        # record does not keep saying WAITING after the receipt says CANCELLED.
        await self._terminalize_observed_nodes(
            run_id,
            RunStatus.CANCELLED,
            error="Canvas generation cancelled",
        )
        refreshed = await self._require_run(run_id)
        if refreshed.status not in TERMINAL_RUN_STATUSES:
            await self._runs.transition_run(run_id, RunStatus.CANCELLED)

    async def fail(self, run_id: str, error: str) -> None:
        """Terminalize a job whose Canvas retry budget is exhausted.

        A worker can disappear while its canonical Attempt is still RUNNING. On
        the final Canvas lease there will be no subsequent retry to fence that
        stale Attempt, so settle it as recovered physical cancellation first.
        The Canvas retry policy then changes the current NodeRun from parked to
        FAILED before terminalizing the Run, making "no more retry" canonical at
        both logical levels.
        """

        run = await self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return
        await self._abandon_active_attempts(run_id, error)
        run = await self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return
        if run.status is not RunStatus.RUNNING:
            await self._resume_for_execution(run_id)
        await self._terminalize_observed_nodes(run_id, RunStatus.FAILED, error=error)
        await self._runs.transition_run(run_id, RunStatus.FAILED, error=error)

    async def _project_stage_result(self, run_id: str, stage: str, result: T) -> T:
        """Apply Canvas-only completion policy after physical evidence is durable.

        Reference generation intentionally stops after the hero call when the
        provider returns no URL. That is existing Canvas behavior and a completed
        job receipt, not a request to execute three impossible refine stages.
        Generic Run reconciliation cannot infer that conditional short-circuit
        from the Graph alone, so Canvas closes the Run explicitly while leaving
        the unexecuted stages absent rather than fabricating NodeRuns/Attempts.
        """

        if stage != "reference.hero" or result != []:
            return result
        run = await self._require_run(run_id)
        if run.status is RunStatus.RUNNING:
            await self._runs.transition_run(run_id, RunStatus.COMPLETED, result=[])
        elif run.status is not RunStatus.COMPLETED:
            raise RunIntegrityError(
                f"Canvas reference short-circuit cannot complete Run from {run.status.value!r}"
            )
        return result

    async def _terminalize_observed_nodes(
        self,
        run_id: str,
        target: RunStatus,
        *,
        error: str,
    ) -> None:
        """Apply Canvas's final retry/cancel decision to materialized NodeRuns."""

        if target not in {RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ValueError("Canvas terminal node projection must be failed or cancelled")
        for node_run in await self._runs.list_node_runs(run_id):
            if node_run.status in TERMINAL_RUN_STATUSES:
                continue
            current = node_run
            for status in transition_path(current.status, target):
                current = await self._runs.transition_node_run(
                    current.node_run_id,
                    status,
                    error=error if status is target else None,
                )

    async def _abandon_active_attempts(self, run_id: str, error: str) -> None:
        """Fence Canvas-worker-loss Attempts before terminal receipt failure."""

        for node_run in await self._runs.list_node_runs(run_id):
            attempts = await self._runs.list_attempts(node_run.node_run_id)
            active = next(
                (
                    attempt
                    for attempt in reversed(attempts)
                    if attempt.status not in TERMINAL_ATTEMPT_STATUSES
                ),
                None,
            )
            if active is not None:
                await self._settle_abandoned_attempt(
                    active,
                    error=error,
                    cancellation=CancellationCause.RECOVERED,
                )

    async def _settle_abandoned_attempt(
        self,
        attempt: Attempt,
        *,
        error: str,
        cancellation: CancellationCause,
    ) -> None:
        """Best-effort stop, then durably fence one stale physical Attempt."""

        with contextlib.suppress(Exception):
            await self._service.cancel_attempt(attempt.attempt_id)

        persisted = await self._runs.get_attempt(attempt.attempt_id)
        if persisted is None:
            raise RunIntegrityError(f"Canvas Attempt {attempt.attempt_id!r} disappeared")
        if persisted.status in TERMINAL_ATTEMPT_STATUSES:
            await self._reconciler.reconcile(persisted, cancellation=cancellation)
            return

        lease = persisted.execution_lease
        if lease is None:
            raise RunIntegrityError(
                f"active Canvas Attempt {persisted.attempt_id!r} has no execution lease"
            )
        try:
            terminal = await self._runs.transition_attempt(
                persisted.attempt_id,
                AttemptStatus.CANCELLED,
                error=error,
                fencing_token=lease.fencing_token,
            )
        except Exception:
            # The old worker may have won the terminal write after our read. Do
            # not turn that benign race into a second effect; accept only a
            # persisted terminal answer and re-raise every other failure.
            raced = await self._runs.get_attempt(persisted.attempt_id)
            if raced is None or raced.status not in TERMINAL_ATTEMPT_STATUSES:
                raise
            terminal = raced
        await self._reconciler.reconcile(terminal, cancellation=cancellation)

    async def _require_run(self, run_id: str) -> Run:
        run = await self._runs.get_run(run_id)
        if run is None:
            raise RunIntegrityError(f"Canvas canonical Run {run_id!r} does not exist")
        return run

    async def _resume_for_execution(self, run_id: str) -> None:
        run = await self._require_run(run_id)
        if run.status is RunStatus.CREATED:
            await self._runs.transition_run(run_id, RunStatus.QUEUED)
            run = await self._require_run(run_id)
        if run.status in {RunStatus.QUEUED, RunStatus.WAITING}:
            await self._runs.transition_run(run_id, RunStatus.RUNNING)
            return
        if run.status is RunStatus.RUNNING:
            return
        if run.status in TERMINAL_RUN_STATUSES:
            raise RunIntegrityError(
                f"Canvas canonical Run {run_id!r} is terminal ({run.status.value})"
            )
        raise RunIntegrityError(
            f"Canvas canonical Run {run_id!r} cannot execute from {run.status.value!r}"
        )

    @staticmethod
    def _stage_node_id(run: Run, stage: str) -> str:
        graph = run.graph.materialize()
        matches = [
            node.node_id for node in graph.nodes if node.metadata.get("canvas_stage") == stage
        ]
        if len(matches) != 1:
            raise RunIntegrityError(
                f"Canvas Run has {len(matches)} nodes for stage {stage!r}; expected exactly one"
            )
        return matches[0]

    async def _node_run(self, run_id: str, node_id: str) -> NodeRun | None:
        matches = [
            node_run
            for node_run in await self._runs.list_node_runs(run_id)
            if node_run.node_id == node_id
        ]
        if len(matches) > 1:
            raise RunIntegrityError(
                f"Canvas Run {run_id!r} has duplicate NodeRuns for node {node_id!r}"
            )
        return matches[0] if matches else None


__all__ = [
    "CanvasCanonicalExecution",
    "canonical_run_id",
    "correlate_run",
]
