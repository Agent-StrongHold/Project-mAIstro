from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NotRequired, Protocol, TypedDict, runtime_checkable

from maistro.projects.scope_store import InMemoryProjectScopeStore, ProjectScopeStore
from maistro.workspaces.model import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceMembership,
    WorkspaceNotFound,
    WorkspaceRole,
)

if TYPE_CHECKING:
    from maistro.personas.store import PersonaStore


class _WorkspaceCreateKwargs(TypedDict):
    name: str
    description: str
    workspace_id: NotRequired[str]
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


@runtime_checkable
class WorkspaceStore(Protocol):
    #: The Project tree paired with this Workspace authority.  Workspace
    #: admission resolves the existing Root Project through this same object.
    #:
    #: Declared as a read-only property, not a plain attribute: concrete
    #: stores (`PgWorkspaceStore`, `SqliteWorkspaceStore`) hold a
    #: `TransactionalProjectScopeStore` here, a distinct (wider) Protocol
    #: than `ProjectScopeStore`. A mutable Protocol attribute is invariant —
    #: it would demand that exact type back — but every consumer only reads
    #: this field, so a covariant read-only property is both correct and
    #: what concrete stores' plain instance attributes already satisfy.
    @property
    def project_store(self) -> ProjectScopeStore: ...

    async def create(
        self,
        *,
        creator_user_id: str,
        name: str,
        description: str = "",
        workspace_id: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> Workspace:
        """Create a Workspace, preserving identity/timestamps only for convergence imports."""
        ...

    async def get(
        self, workspace_id: str, *, principal_id: str | None = None
    ) -> Workspace | None: ...

    async def update(
        self, workspace: Workspace, *, principal_id: str | None = None
    ) -> Workspace: ...

    async def delete(self, workspace_id: str, *, principal_id: str | None = None) -> None: ...

    async def list_for_user(self, user_id: str) -> list[Workspace]: ...

    async def list_memberships(
        self, workspace_id: str, *, principal_id: str | None = None
    ) -> list[WorkspaceMembership]: ...

    async def get_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
        principal_id: str | None = None,
    ) -> WorkspaceMembership | None: ...

    async def lock_and_read_membership(
        self,
        conn: Any,
        workspace_id: str,
        *,
        user_id: str,
    ) -> WorkspaceMembership | None:
        """Read one membership on a connection the caller already holds.

        The durable stores answer this *after* taking the Workspace's own
        serialization point -- PostgreSQL's ``SELECT ... FOR UPDATE`` on the
        Workspace row, SQLite's ``BEGIN IMMEDIATE`` the caller already
        holds -- so a caller that is about to write can ask for authority on
        its own connection and be serialized against a concurrent
        revocation of it (#1150). The in-memory reference has no such race:
        it has no await between the decision and the write, so it answers
        from its map.

        ``conn`` is the connection the write will happen on. Reading the
        membership anywhere else -- a second pooled connection, or before
        the lock -- answers a question that may already have changed.
        """
        ...

    async def set_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
        role: WorkspaceRole,
        principal_id: str | None = None,
    ) -> WorkspaceMembership: ...

    async def remove_membership(
        self, workspace_id: str, *, user_id: str, principal_id: str | None = None
    ) -> None: ...


class InMemoryWorkspaceStore:
    """Reference Workspace store that atomically provisions the Root Project."""

    def __init__(
        self,
        *,
        project_store: ProjectScopeStore | None = None,
        persona_store: PersonaStore | None = None,
    ) -> None:
        self._workspaces: dict[str, Workspace] = {}
        self._memberships: dict[tuple[str, str], WorkspaceMembership] = {}
        self.project_store: ProjectScopeStore = project_store or InMemoryProjectScopeStore()
        # Pairing is the composition point: the Project store resolves scope
        # through this Workspace store, so binding here means a caller cannot
        # construct the canonical pair and leave the boundary unwired (#1150).
        self.project_store.bind_workspace_store(self)
        self.persona_store = persona_store

    async def create(
        self,
        *,
        creator_user_id: str,
        name: str,
        description: str = "",
        workspace_id: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> Workspace:
        """Create canonical identity, optionally retaining convergence metadata.

        Ordinary callers omit ``workspace_id`` and both timestamps, so the
        canonical model mints/stamps them. The explicit forms exist only so a
        product adapter can retire a durable legacy Workspace without inventing
        an old→new identity map or rewriting its chronology (#37).
        """
        workspace_kwargs: _WorkspaceCreateKwargs = {"name": name, "description": description}
        if workspace_id is not None:
            workspace_kwargs["workspace_id"] = workspace_id
        if created_at is not None:
            workspace_kwargs["created_at"] = created_at
        if updated_at is not None:
            workspace_kwargs["updated_at"] = updated_at
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
        except BaseException:
            del self._workspaces[workspace.workspace_id]
            del self._memberships[(workspace.workspace_id, creator_user_id)]
            # A failing scope backend may have persisted the Root before
            # reporting the failure; remove it so the operation is atomic in
            # the reference store as well as in the durable transactions.
            await self.project_store.purge_workspace(workspace.workspace_id)
            raise
        return workspace.model_copy(deep=True)

    async def get(self, workspace_id: str, *, principal_id: str | None = None) -> Workspace | None:
        from maistro.workspaces.authorization import WorkspaceAuthorizationDenied
        from maistro.workspaces.store_boundary import is_blank_principal, require_workspace_view

        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            return None
        if principal_id is not None:
            if is_blank_principal(principal_id):
                raise WorkspaceAuthorizationDenied
            await require_workspace_view(self, workspace_id, principal_id)
        return workspace.model_copy(deep=True)

    async def update(self, workspace: Workspace, *, principal_id: str | None = None) -> Workspace:
        from maistro.workspaces.authorization import WorkspaceAuthorizationDenied
        from maistro.workspaces.store_boundary import is_blank_principal, require_workspace_view

        if workspace.workspace_id not in self._workspaces:
            raise WorkspaceNotFound(workspace.workspace_id)
        if principal_id is not None:
            if is_blank_principal(principal_id):
                raise WorkspaceAuthorizationDenied
            await require_workspace_view(self, workspace.workspace_id, principal_id)
        updated = workspace.model_copy(update={"updated_at": datetime.now(UTC)})
        self._workspaces[workspace.workspace_id] = updated
        return updated.model_copy(deep=True)

    async def delete(self, workspace_id: str) -> None:
        """Remove the Workspace, its memberships, and its Projects.

        The reference has no transaction, so it compensates the way `create`
        does: the Workspace and membership entries come out first and go back
        if the purge raises, so a failure in either half leaves everything as
        it was (#1121). The durable stores do both halves in one transaction
        and need no restore; the contract the conformance suite reads is the
        same.
        """
        if workspace_id not in self._workspaces:
            raise WorkspaceNotFound(workspace_id)
        workspace, memberships = await self._delete_workspace_row(workspace_id)

        # A direct call, not `getattr(store, "purge_workspace", None)`. The
        # optional form meant the Projects were purged in tests, where the
        # store was the in-memory reference, and left orphaned on every durable
        # deployment, where no implementation defined it (Codex, #516).
        try:
            await self.project_store.purge_workspace(workspace_id)
        except Exception:
            self._workspaces[workspace_id] = workspace
            self._memberships.update(memberships)
            raise

    async def _delete_workspace_row(
        self, workspace_id: str
    ) -> tuple[Workspace, dict[tuple[str, str], WorkspaceMembership]]:
        """Take the Workspace and its memberships out, returning them for a restore."""
        workspace = self._workspaces.pop(workspace_id)
        memberships = {
            key: self._memberships[key] for key in self._memberships if key[0] == workspace_id
        }
        for key in memberships:
            del self._memberships[key]
        return workspace, memberships

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

    async def list_memberships(
        self, workspace_id: str, *, principal_id: str | None = None
    ) -> list[WorkspaceMembership]:
        from maistro.workspaces.store_boundary import authorize_workspace_view

        await authorize_workspace_view(self, workspace_id, principal_id)
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
        principal_id: str | None = None,
    ) -> WorkspaceMembership | None:
        from maistro.workspaces.store_boundary import authorize_workspace_view

        await authorize_workspace_view(self, workspace_id, principal_id)
        self._require_workspace(workspace_id)
        membership = self._memberships.get((workspace_id, user_id))
        return membership.model_copy(deep=True) if membership is not None else None

    async def set_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
        role: WorkspaceRole,
        principal_id: str | None = None,
    ) -> WorkspaceMembership:
        from maistro.workspaces.store_boundary import authorize_workspace_administer

        await authorize_workspace_administer(self, workspace_id, principal_id)
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

    async def remove_membership(
        self, workspace_id: str, *, user_id: str, principal_id: str | None = None
    ) -> None:
        from maistro.workspaces.store_boundary import authorize_membership_removal

        await authorize_membership_removal(
            self, workspace_id, user_id=user_id, principal_id=principal_id
        )
        self._require_workspace(workspace_id)
        key = (workspace_id, user_id)
        existing = self._memberships.get(key)
        if existing is None:
            return
        if existing.role is WorkspaceRole.OWNER:
            self._ensure_another_owner(workspace_id, excluding_user_id=user_id)
        del self._memberships[key]

    async def lock_and_read_membership(
        self,
        conn: Any,
        workspace_id: str,
        *,
        user_id: str,
    ) -> WorkspaceMembership | None:
        """One membership, from the map, on the caller's connection.

        The reference store is single-threaded and has no await between a
        decision and the write it guards, so there is no window for a
        revocation to slip through and no lock to take.
        """
        membership = self._memberships.get((workspace_id, user_id))
        return membership.model_copy(deep=True) if membership is not None else None

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
