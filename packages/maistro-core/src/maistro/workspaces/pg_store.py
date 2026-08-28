"""PostgreSQL authority for canonical Workspace and WorkspaceMembership state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.projects.scope import Project
from maistro.runs.evidence_json import json_of, model_of
from maistro.workspaces.model import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceMembership,
    WorkspaceNotFound,
    WorkspaceOwnershipError,
    WorkspaceRole,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg


class PgWorkspaceStore:
    """Durable Workspace identity/membership owner for PostgreSQL deployments.

    Workspace creation, its initial OWNER membership, and its Root Project are
    one transaction. Membership mutations lock the Workspace row, which makes
    the "at least one owner" invariant hold under concurrent replicas rather
    than only inside one process.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        project_store: PgProjectScopeStore | None = None,
    ) -> None:
        self._pool = pool
        self.project_store = project_store or PgProjectScopeStore(pool)

    async def create(
        self,
        *,
        creator_user_id: str,
        name: str,
        description: str = "",
    ) -> Workspace:
        workspace = Workspace(name=name, description=description)
        owner = WorkspaceMembership(
            workspace_id=workspace.workspace_id,
            user_id=creator_user_id,
            role=WorkspaceRole.OWNER,
            added_at=workspace.created_at,
        )
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO canonical_workspaces (workspace_id, payload)
                   VALUES ($1, $2::text::jsonb)""",
                workspace.workspace_id,
                json_of(workspace),
            )
            await self._write_membership(conn, owner)
            # PgProjectScopeStore currently owns its connection acquisition.
            # Calling it here would commit Workspace identity before Root
            # Project creation. Provision the same canonical Project row in the
            # caller-owned transaction instead; the existing partial unique
            # index remains the one-root authority.
            await self._create_root(conn, workspace.workspace_id)
        return workspace.model_copy(deep=True)

    async def get(self, workspace_id: str) -> Workspace | None:
        async with self._pool.acquire() as conn:
            payload = await conn.fetchval(
                "SELECT payload FROM canonical_workspaces WHERE workspace_id = $1",
                workspace_id,
            )
        return model_of(Workspace, payload) if payload is not None else None

    async def update(self, workspace: Workspace) -> Workspace:
        updated = workspace.model_copy(update={"updated_at": datetime.now(UTC)})
        async with self._pool.acquire() as conn:
            status = await conn.execute(
                """UPDATE canonical_workspaces
                      SET payload = $1::text::jsonb
                    WHERE workspace_id = $2""",
                json_of(updated),
                workspace.workspace_id,
            )
        if status == "UPDATE 0":
            raise WorkspaceNotFound(workspace.workspace_id)
        return updated.model_copy(deep=True)

    async def delete(self, workspace_id: str) -> None:
        """Delete an otherwise-empty Workspace and its implicit Root Project.

        Project/Run history is durable evidence and must not disappear through a
        Workspace delete. A Workspace with non-root Projects or any Project-
        scoped durable rows therefore fails closed rather than cascading.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await self._lock_workspace(conn, workspace_id)
            project_rows = await conn.fetch(
                """SELECT project_id, is_root
                     FROM canonical_projects
                    WHERE workspace_id = $1
                    FOR UPDATE""",
                workspace_id,
            )
            if any(not bool(row["is_root"]) for row in project_rows):
                raise WorkspaceOwnershipError("Workspace with child Projects cannot be deleted")
            project_ids = [str(row["project_id"]) for row in project_rows]
            if project_ids:
                for table in (
                    "canonical_runs",
                    "canonical_project_memberships",
                    "canonical_project_resources",
                ):
                    exists = await conn.fetchval(
                        f"SELECT 1 FROM {table} WHERE project_id = ANY($1::text[]) LIMIT 1",
                        project_ids,
                    )
                    if exists is not None:
                        raise WorkspaceOwnershipError(
                            "Workspace with project-scoped durable state cannot be deleted"
                        )
                await conn.execute(
                    "DELETE FROM canonical_projects WHERE workspace_id = $1 AND is_root",
                    workspace_id,
                )
            await conn.execute(
                "DELETE FROM canonical_workspaces WHERE workspace_id = $1",
                workspace_id,
            )

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT w.payload
                     FROM canonical_workspaces AS w
                     JOIN canonical_workspace_memberships AS m
                       ON m.workspace_id = w.workspace_id
                    WHERE m.user_id = $1""",
                user_id,
            )
        workspaces = [model_of(Workspace, row["payload"]) for row in rows]
        workspaces.sort(key=lambda item: item.created_at, reverse=True)
        return workspaces

    async def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]:
        await self._require_workspace(workspace_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload
                     FROM canonical_workspace_memberships
                    WHERE workspace_id = $1""",
                workspace_id,
            )
        memberships = [model_of(WorkspaceMembership, row["payload"]) for row in rows]
        memberships.sort(key=lambda item: (item.added_at, item.user_id))
        return memberships

    async def get_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
    ) -> WorkspaceMembership | None:
        await self._require_workspace(workspace_id)
        async with self._pool.acquire() as conn:
            payload = await conn.fetchval(
                """SELECT payload
                     FROM canonical_workspace_memberships
                    WHERE workspace_id = $1 AND user_id = $2""",
                workspace_id,
                user_id,
            )
        return model_of(WorkspaceMembership, payload) if payload is not None else None

    async def set_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
        role: WorkspaceRole,
    ) -> WorkspaceMembership:
        async with self._pool.acquire() as conn, conn.transaction():
            await self._lock_workspace(conn, workspace_id)
            payload = await conn.fetchval(
                """SELECT payload
                     FROM canonical_workspace_memberships
                    WHERE workspace_id = $1 AND user_id = $2""",
                workspace_id,
                user_id,
            )
            existing = model_of(WorkspaceMembership, payload) if payload is not None else None
            if (
                existing is not None
                and existing.role is WorkspaceRole.OWNER
                and role is not WorkspaceRole.OWNER
            ):
                await self._require_other_owner(conn, workspace_id, excluding_user_id=user_id)
            membership = WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=user_id,
                role=role,
                added_at=existing.added_at if existing is not None else datetime.now(UTC),
            )
            await self._write_membership(conn, membership)
        return membership.model_copy(deep=True)

    async def remove_membership(self, workspace_id: str, *, user_id: str) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await self._lock_workspace(conn, workspace_id)
            row = await conn.fetchrow(
                """SELECT role
                     FROM canonical_workspace_memberships
                    WHERE workspace_id = $1 AND user_id = $2""",
                workspace_id,
                user_id,
            )
            if row is None:
                return
            if str(row["role"]) == WorkspaceRole.OWNER.value:
                await self._require_other_owner(conn, workspace_id, excluding_user_id=user_id)
            await conn.execute(
                """DELETE FROM canonical_workspace_memberships
                    WHERE workspace_id = $1 AND user_id = $2""",
                workspace_id,
                user_id,
            )

    async def _require_workspace(self, workspace_id: str) -> Workspace:
        workspace = await self.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFound(workspace_id)
        return workspace

    async def _lock_workspace(self, conn: Any, workspace_id: str) -> None:
        found = await conn.fetchval(
            """SELECT workspace_id
                 FROM canonical_workspaces
                WHERE workspace_id = $1
                FOR UPDATE""",
            workspace_id,
        )
        if found is None:
            raise WorkspaceNotFound(workspace_id)

    async def _require_other_owner(
        self,
        conn: Any,
        workspace_id: str,
        *,
        excluding_user_id: str,
    ) -> None:
        other = await conn.fetchval(
            """SELECT 1
                 FROM canonical_workspace_memberships
                WHERE workspace_id = $1
                  AND user_id <> $2
                  AND role = 'owner'
                LIMIT 1""",
            workspace_id,
            excluding_user_id,
        )
        if other is None:
            raise WorkspaceAccessDenied("a Workspace must retain at least one owner")

    @staticmethod
    async def _create_root(conn: Any, workspace_id: str) -> Project:
        root = Project(
            workspace_id=workspace_id,
            name="Root",
            parent_project_id=None,
            is_root=True,
        )
        await conn.execute(
            """INSERT INTO canonical_projects
               (project_id, workspace_id, parent_project_id, is_root, payload)
               VALUES ($1, $2, NULL, TRUE, $3::text::jsonb)
               ON CONFLICT DO NOTHING""",
            root.project_id,
            root.workspace_id,
            json_of(root),
        )
        payload = await conn.fetchval(
            """SELECT payload FROM canonical_projects
                WHERE workspace_id = $1 AND is_root""",
            workspace_id,
        )
        if payload is None:  # pragma: no cover - guarded by the same transaction
            raise WorkspaceOwnershipError("Workspace Root Project was not persisted")
        return model_of(Project, payload)

    @staticmethod
    async def _write_membership(conn: Any, membership: WorkspaceMembership) -> None:
        await conn.execute(
            """INSERT INTO canonical_workspace_memberships
               (workspace_id, user_id, role, payload)
               VALUES ($1, $2, $3, $4::text::jsonb)
               ON CONFLICT (workspace_id, user_id) DO UPDATE
               SET role = EXCLUDED.role, payload = EXCLUDED.payload""",
            membership.workspace_id,
            membership.user_id,
            membership.role.value,
            json_of(membership),
        )


__all__ = ["PgWorkspaceStore"]
