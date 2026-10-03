"""Workspace-membership scope gate for RunStore by-id operations (#364)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.projects.scope_store import ProjectScopeStore
    from maistro.runs.model import Attempt, NodeRun, Run
    from maistro.runs.store import RunStore
    from maistro.workspaces.store import WorkspaceStore


class RunStoreBoundary:
    def __init__(
        self,
        run_store: RunStore,
        workspace_store: WorkspaceStore,
        project_store: ProjectScopeStore,
    ) -> None:
        self._run_store = run_store
        self._workspace_store = workspace_store
        self._project_store = project_store

    def _reader(self):
        from maistro.runs.scoped_reads import ScopedRunReader

        return ScopedRunReader(self._run_store, self._workspace_store, self._project_store)

    async def require_run(self, run_id: str, *, principal_id: str) -> Run:
        return await self._reader().get_run(run_id, principal_id=principal_id)

    async def require_node_run(self, node_run_id: str, *, principal_id: str) -> NodeRun:
        from maistro.runs.scoped_reads import RunNotVisible

        node_run = await self._run_store.get_node_run(node_run_id)
        if node_run is None:
            raise RunNotVisible
        await self._reader().get_run(node_run.run_id, principal_id=principal_id)
        return node_run

    async def require_attempt(self, attempt_id: str, *, principal_id: str) -> Attempt:
        from maistro.runs.scoped_reads import RunNotVisible

        attempt = await self._run_store.get_attempt(attempt_id)
        if attempt is None:
            raise RunNotVisible
        node_run = await self._run_store.get_node_run(attempt.node_run_id)
        if node_run is None:
            raise RunNotVisible
        await self._reader().get_run(node_run.run_id, principal_id=principal_id)
        return attempt


def require_admitted_actor(actor_principal_id: str | None) -> str:
    if actor_principal_id is None or not str(actor_principal_id).strip():
        raise ValueError("actor_principal_id is required")
    return str(actor_principal_id).strip()


__all__ = ["RunStoreBoundary", "require_admitted_actor"]
