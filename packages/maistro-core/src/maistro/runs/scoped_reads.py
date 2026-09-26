"""Workspace-membership-scoped reads of the canonical Run tree (#1152).

`RunStore` answers whoever holds an id. This is the product read seam: a
principal may read a Run, its NodeRuns and its Attempts when they are a member
of the Run's Workspace and the Run's Project belongs to that Workspace. The
initiating principal (`Run.actor_principal_id`) is provenance, not a gate.

Every refusal is one `RunNotVisible` -- missing, foreign, blank principal, or
a child id that belongs to another Run -- so no answer confirms an id exists.
"""

from __future__ import annotations

from contextlib import suppress

from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.model import Attempt, NodeRun, Run
from maistro.runs.store import RunStore
from maistro.workspaces.authorization import (
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
)
from maistro.workspaces.store import WorkspaceStore


class RunNotVisible(LookupError):
    """The Run (or a child of it) does not exist for this principal."""

    def __init__(self) -> None:
        super().__init__("Run not found")


class ScopedRunReader:
    def __init__(
        self,
        run_store: RunStore,
        workspace_store: WorkspaceStore,
        project_store: ProjectScopeStore,
    ) -> None:
        self.run_store = run_store
        self.workspace_store = workspace_store
        self.project_store = project_store
        self._authorizer = WorkspaceAuthorizer(workspace_store)

    async def get_run(self, run_id: str, *, principal_id: str) -> Run:
        return await self._visible_run(run_id, principal_id)

    async def list_node_runs(self, run_id: str, *, principal_id: str) -> list[NodeRun]:
        run = await self._visible_run(run_id, principal_id)
        return await self.run_store.list_node_runs(run.run_id)

    async def get_node_run(self, run_id: str, node_run_id: str, *, principal_id: str) -> NodeRun:
        run = await self._visible_run(run_id, principal_id)
        return await self._node_run_of(run, node_run_id)

    async def list_attempts(
        self, run_id: str, node_run_id: str, *, principal_id: str
    ) -> list[Attempt]:
        run = await self._visible_run(run_id, principal_id)
        node_run = await self._node_run_of(run, node_run_id)
        return await self.run_store.list_attempts(node_run.node_run_id)

    async def get_attempt(self, run_id: str, attempt_id: str, *, principal_id: str) -> Attempt:
        run = await self._visible_run(run_id, principal_id)
        attempt = await self.run_store.get_attempt(attempt_id)
        if attempt is None:
            raise RunNotVisible
        await self._node_run_of(run, attempt.node_run_id)
        return attempt

    async def _node_run_of(self, run: Run, node_run_id: str) -> NodeRun:
        node_run = await self.run_store.get_node_run(node_run_id)
        if node_run is None or node_run.run_id != run.run_id:
            raise RunNotVisible
        return node_run

    async def _visible_run(self, run_id: str, principal_id: str) -> Run:
        # The principal's Workspaces are resolved before, and independently
        # of, the Run lookup, so a missing id and a foreign id do the same
        # membership work and neither latency nor answer confirms existence.
        member_of = await self._member_workspace_ids(principal_id)
        run = await self.run_store.get_run(run_id)
        if run is None or run.workspace_id not in member_of:
            raise RunNotVisible
        membership = None
        with suppress(WorkspaceAuthorizationDenied):
            membership = await self._authorizer.require(
                principal_id, run.workspace_id, WorkspaceAction.VIEW
            )
        project = await self.project_store.get(run.project_id)
        if membership is None or project is None or project.workspace_id != run.workspace_id:
            raise RunNotVisible
        return run

    async def _member_workspace_ids(self, principal_id: str) -> frozenset[str]:
        if not isinstance(principal_id, str) or not principal_id.strip():
            return frozenset()
        workspaces = await self.workspace_store.list_for_user(principal_id)
        return frozenset(workspace.workspace_id for workspace in workspaces)


__all__ = ["RunNotVisible", "ScopedRunReader"]
