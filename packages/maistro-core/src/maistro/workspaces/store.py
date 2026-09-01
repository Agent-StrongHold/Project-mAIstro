from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.projects.scope_store import InMemoryProjectScopeStore, ProjectScopeStore
from maistro.workspaces.model import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceMembership,
    WorkspaceNotFound,
    WorkspaceRole,
)


@runtime_checkable
class WorkspaceStore(Protocol):
    async def create(
        self,
        *,
        creator_user_id: str,
        name: str,
        description: str = "",
        workspace_id: str | None = None,
    ) -> Workspace:
        """Create a Workspace, preserving an existing ID only for convergence imports."""
        ...

    async def get(self, workspace_id: str) -> Workspace | None: ...

    async def update(self, workspace: Workspace) -> Workspace: ...

    async def delete(self, workspace_id: str) -> None: ...

    async def list_for_user(self, user_id: str) -> list[Workspace]: ...

    async def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]: ...

    async def get_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
    ) -> WorkspaceMembership | None: ...

    async def set_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
        role: WorkspaceRole,
    ) -> WorkspaceMembership: ...

    async def remove_membership(self, workspace_id: str, *, user_id: str) -> None: ...


class InMemoryWorkspaceStore:
    """Reference Workspace store that atomically provisions the Root Project."""

    def __init__(self, *, project_store: ProjectScopeStore | None = None) -> None:
        self._workspaces: dict[str, Workspace] = {}
        self._memberships: dict[tuple[str, str], WorkspaceMembership] = {}
        self.project_store: ProjectScopeStore = project_store or InMemoryProjectScopeStore()

    async def create(
        self,
        *,
        creator_user_id: str,
        name: str,
        description: str = "",
        workspace_id: str | None = None,
    ) -> Workspace:
        """Create canonical identity, optionally retaining a pre-convergence ID.

        Ordinary callers omit ``workspace_id`` and the canonical model mints it.
        The explicit form exists only so a product adapter can retire a durable
        legacy Workspace without inventing an old→new identity mapping (#37).
        It is still a canonical insert: duplicate IDs are refused and the Root
        Project is provisioned by this store exactly as for a new Workspace.
        """
        workspace_kwargs: dict[str, str] = {"name": name, "description": description}
        if workspace_id is not None:
            workspace_kwargs["workspace_id"] = workspace_id
        workspace = Workspace(**workspace_kwargs)
        if workspace.workspace_id in self._workspaces:
            raise ValueError(f"Workspace {workspace.workspace_id!r} already exists")
        owner = WorkspaceMembership(
            workspace_id=workspace.workspace_id,
            user_id=creator_user_id,
            role=WorkspaceRole.OWNER,
            added_at=workspace.created_at,
        )
        self._workspaces[workspace.workspace_id] = workspace
        self._memberships[(workspace.workspace_id, creator_user_id)] = owner
        try:
            await self.project_store.create_root(workspace.workspace_id)
        except Exception:
            del self._workspaces[workspace.workspace_id]
            del self._memberships[(workspace.workspace_id, creator_user_id)]
            raise
        return workspace.model_copy(deep=True)

    async def get(self, workspace_id: str) -> Workspace | None:
        workspace = self._workspaces.get(workspace_id)
        return workspace.model_copy(deep=True) if workspace is not None else None

    async def update(self, workspace: Workspace) -> Workspace:
        if workspace.workspace_id not in self._workspaces:
            raise WorkspaceNotFound(workspace.workspace_id)
        updated = workspace.model_copy(update={"updated_at": datetime.now(UTC)})
        self._workspaces[workspace.workspace_id] = updated
        return updated.model_copy(deep=True)

    async def delete(self, workspace_id: str) -> None:
        if workspace_id not in self._workspaces:
            raise WorkspaceNotFound(workspace_id)
        del self._workspaces[workspace_id]
        for key in [key for key in self._memberships if key[0] == workspace_id]:
            del self._memberships[key]

        # A direct call, not `getattr(store, "purge_workspace", None)`. The
        # optional form meant the Projects were purged in tests, where the
        # store was the in-memory reference, and left orphaned on every durable
        # deployment, where no implementation defined it (Codex, #516).
        await self.project_store.purge_workspace(workspace_id)

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        workspace_ids = {
            workspace_id
            for (workspace_id, member_user_id) in self._memberships
            if member_user_id == user_id
        }
        workspaces = [
            self._workspaces[workspace_id].model_copy(deep=True)
            for workspace_id in workspace_ids
            if workspace_id in self._workspaces
        ]
        workspaces.sort(key=lambda item: item.created_at, reverse=True)
        return workspaces

    async def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]:
        self._require_workspace(workspace_id)
        memberships = [
            membership.model_copy(deep=True)
            for (member_workspace_id, _), membership in self._memberships.items()
            if member_workspace_id == workspace_id
        ]
        memberships.sort(key=lambda item: (item.added_at, item.user_id))
        return memberships

    async def get_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
    ) -> WorkspaceMembership | None:
        self._require_workspace(workspace_id)
        membership = self._memberships.get((workspace_id, user_id))
        return membership.model_copy(deep=True) if membership is not None else None

    async def set_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
        role: WorkspaceRole,
    ) -> WorkspaceMembership:
        self._require_workspace(workspace_id)
        existing = self._memberships.get((workspace_id, user_id))
        if (
            existing is not None
            and existing.role is WorkspaceRole.OWNER
            and role is not WorkspaceRole.OWNER
        ):
            self._ensure_another_owner(workspace_id, excluding_user_id=user_id)

        membership = WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
            added_at=existing.added_at if existing is not None else datetime.now(UTC),
        )
        self._memberships[(workspace_id, user_id)] = membership
        return membership.model_copy(deep=True)

    async def remove_membership(self, workspace_id: str, *, user_id: str) -> None:
        self._require_workspace(workspace_id)
        key = (workspace_id, user_id)
        existing = self._memberships.get(key)
        if existing is None:
            return
        if existing.role is WorkspaceRole.OWNER:
            self._ensure_another_owner(workspace_id, excluding_user_id=user_id)
        del self._memberships[key]

    def _require_workspace(self, workspace_id: str) -> Workspace:
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFound(workspace_id)
        return workspace

    def _ensure_another_owner(self, workspace_id: str, *, excluding_user_id: str) -> None:
        has_other_owner = any(
            member_workspace_id == workspace_id
            and member_user_id != excluding_user_id
            and membership.role is WorkspaceRole.OWNER
            for (member_workspace_id, member_user_id), membership in self._memberships.items()
        )
        if not has_other_owner:
            raise WorkspaceAccessDenied("a Workspace must retain at least one owner")


__all__ = ["InMemoryWorkspaceStore", "WorkspaceStore"]
