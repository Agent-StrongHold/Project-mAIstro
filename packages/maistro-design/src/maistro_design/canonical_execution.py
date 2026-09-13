"""Canonical execution adapter for Design Studio project operations.

Design owns the project and artifact projection. The canonical RunStore owns
execution identity and physical Attempt evidence; this adapter only translates
one Design operation into that shared spine.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from maistro.graph.definitions import Graph, Node
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import TERMINAL_RUN_STATUSES, AttemptStatus, Run, RunStatus
from maistro.runs.service import RunExecutionService
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runtime import ExecutionRuntime, PythonExecutionRuntime

T = TypeVar("T")

_SOURCE = "design_studio"
_EXECUTOR_ID = "design_engine"


class DesignCanonicalExecution:
    """Execute Design operations under an authorized Workspace/Project.

    ``workspace_id`` and ``project_id`` are constructor bindings supplied by
    the canonical owner. Design identifiers (project rows, canvases, or orgs)
    are never used to manufacture this scope.
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

    async def admit(
        self,
        *,
        discovery: Any,
        actor_principal_id: str | None,
    ) -> str:
        """Admit one Design operation as one immutable canonical Graph/Run."""
        skill_slug = str(getattr(discovery, "skill_slug", ""))
        system_slug = str(getattr(discovery, "design_system_slug", ""))
        node_id = f"design:project:{skill_slug}:{system_slug}"
        graph = Graph(
            graph_id=f"design:{self._workspace_id}:{self._project_id}:{node_id}",
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            name="Design Studio project operation",
            nodes=[
                Node(
                    node_id=node_id,
                    node_type="design.project",
                    name="Design project operation",
                    parameters={"skill_slug": skill_slug, "design_system_slug": system_slug},
                    metadata={"design_source": _SOURCE},
                )
            ],
            metadata={"design_source": _SOURCE},
        )
        run = await self._service.create_run(
            graph,
            actor_principal_id=actor_principal_id,
            provenance={
                "admission_source": _SOURCE,
                "design_skill_slug": skill_slug,
                "design_system_slug": system_slug,
            },
        )
        try:
            await self._runs.transition_run(run.run_id, RunStatus.QUEUED)
        except BaseException:
            with contextlib.suppress(Exception):
                await self._runs.transition_run(run.run_id, RunStatus.CANCELLED)
                await self._runs.delete_run(run.run_id)
            raise
        return cast(str, run.run_id)

    async def generate(
        self,
        *,
        discovery: Any,
        operation: Callable[[], Awaitable[T]],
        actor_principal_id: str | None,
    ) -> T:
        """Admit and execute one Design operation through the canonical spine."""
        run_id = await self.admit(
            discovery=discovery,
            actor_principal_id=actor_principal_id,
        )
        return await self.execute(run_id, operation)

    async def execute(
        self,
        run_id: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        """Run one Design operation and return its domain projection.

        A provider failure leaves a failed Attempt as the physical truth, then
        this adapter applies Design's no-retry-for-this-request policy to the
        logical NodeRun/Run without hiding the failed Attempt.
        """
        run = await self._require_run(run_id)
        graph = run.graph.materialize()
        node_id = graph.nodes[0].node_id
        node_run = await self._node_run_for_node(run_id, node_id)
        if node_run is not None and node_run.status is RunStatus.COMPLETED:
            attempts = await self._runs.list_attempts(node_run.node_run_id)
            completed = next(
                (item for item in reversed(attempts) if item.status is AttemptStatus.COMPLETED),
                None,
            )
            if completed is None:
                raise RunIntegrityError("completed Design NodeRun has no completed Attempt")
            return cast(T, completed.result)

        captured: list[T] = []

        async def _execute(_work_item: object, _context: object) -> T:
            result = await operation()
            captured.append(result)
            return result

        try:
            _node_run, attempt = await self._service.execute_node(
                run_id,
                node_id,
                None,
                {"run_id": run_id, "node_id": node_id, "design_source": _SOURCE},
                executor=_execute,
                executor_id=_EXECUTOR_ID,
            )
        except BaseException as exc:
            await self.fail(run_id, str(exc))
            raise
        if captured:
            return captured[0]
        if attempt.status is AttemptStatus.COMPLETED:
            return cast(T, attempt.result)
        raise RunIntegrityError("Design operation returned without a completed Attempt result")

    async def fail(self, run_id: str, error: str) -> None:
        """Apply the terminal no-retry decision without erasing Attempt evidence."""
        run = await self._require_run(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return
        if run.status is not RunStatus.RUNNING:
            await self._resume_for_execution(run_id)
        for node_run in await self._runs.list_node_runs(run_id):
            current = node_run
            if current.status in TERMINAL_RUN_STATUSES:
                continue
            for status in transition_path(current.status, RunStatus.FAILED):
                current = await self._runs.transition_node_run(
                    current.node_run_id,
                    status,
                    error=error if status is RunStatus.FAILED else None,
                )
        refreshed = await self._require_run(run_id)
        if refreshed.status not in TERMINAL_RUN_STATUSES:
            await self._runs.transition_run(run_id, RunStatus.FAILED, error=error)

    async def _resume_for_execution(self, run_id: str) -> None:
        run = await self._require_run(run_id)
        if run.status is RunStatus.CREATED:
            await self._runs.transition_run(run_id, RunStatus.QUEUED)
            run = await self._require_run(run_id)
        if run.status in {RunStatus.QUEUED, RunStatus.WAITING}:
            await self._runs.transition_run(run_id, RunStatus.RUNNING)
        elif run.status is not RunStatus.RUNNING:
            raise RunIntegrityError(
                f"Design Run {run_id!r} cannot execute from {run.status.value!r}"
            )

    async def _node_run_for_node(self, run_id: str, node_id: str) -> Any:
        node_runs = await self._runs.list_node_runs(run_id)
        matches = [item for item in node_runs if item.node_id == node_id]
        if len(matches) > 1:
            raise RunIntegrityError(f"Design Run has multiple NodeRuns for node {node_id!r}")
        return matches[0] if matches else None

    async def _require_run(self, run_id: str) -> Run:
        run = await self._runs.get_run(run_id)
        if run is None:
            raise RunIntegrityError(f"Design canonical Run {run_id!r} does not exist")
        if (run.workspace_id, run.project_id) != (self._workspace_id, self._project_id):
            raise RunIntegrityError(
                f"Design canonical Run {run_id!r} is outside its bound Workspace/Project scope"
            )
        return run


__all__ = ["DesignCanonicalExecution"]
