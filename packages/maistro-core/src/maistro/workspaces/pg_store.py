"""PostgreSQL persistence for the canonical Workspace (#516).

The durable twin of `sqlite_store.py` and of `InMemoryWorkspaceStore`, which
stays the reference the other two are read against. One conformance suite runs
one set of bodies over all three, because "implements the same protocol as"
being a docstring rather than a test is how `PgStrikeTracker` came to be
unusable (#134).

What differs from the reference is not the SQL but the concurrency, and it
concentrates in one rule: **a Workspace must retain at least one owner.**
`InMemoryWorkspaceStore` enforces it by reading the roster and then writing,
which is correct in a single event loop and wrong the moment two processes do
it at once. Two callers each demoting one of the last two owners both see the
*other* owner, both proceed, and the Workspace ends up with none — a Workspace
no route can administer, produced by two operations that individually obeyed
the rule.

So every write that could remove the last owner takes `SELECT ... FOR UPDATE`
on the Workspace row first. The lock is not protecting the Workspace row's
contents; it is the serialisation point for the membership rows beneath it,
which is the only place a "how many owners are left" question can be asked and
answered atomically. `create` takes it too, so a demotion cannot interleave
with the owner membership being written.

A `CHECK` constraint cannot express this — it sees one row, and the rule is
about a set. A deferred constraint trigger could, at the cost of putting the
invariant in a second place that has to agree with this one; the row lock keeps
it in the store, where the reference implementation's version of the same rule
already lives.

Payloads are JSONB and come back as dicts, because the pool registers a JSON
codec (`maistro.persistence._register_json_codecs`). That is why this reads
`model_of` where the SQLite store parses text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.runs.evidence_json import json_of, model_of
from maistro.workspaces.model import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceMembership,
    WorkspaceNotFound,
    WorkspaceRole,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

    from maistro.projects.scope_store import ProjectScopeStore


class PgWorkspaceStore:
    """Durable Workspace identity and membership store."""

    def __init__(self, pool: asyncpg.Pool, *, project_store: ProjectScopeStore) -> None:
        self._pool = pool
        #: Public for the same reason `InMemoryWorkspaceStore` exposes it: the
        #: Root Project a Workspace owns is reached through the Workspace, and a
        #: caller that resolved a second scope store of its own would be filing
        #: Projects in a tree this store never provisions.
        self.project_store: ProjectScopeStore = project_store

    async def create(
        self,
        *,
        creator_user_id: str,
        name: str,
        description: str = "",
    ) -> Workspace:
        """Write the Workspace, its owner membership, and its Root Project.

        The two row writes share a transaction, so a Workspace never exists
        without the owner that was created with it. The Root Project is the
        other store's write and cannot join that transaction, so it keeps the
        reference's compensating delete: if `create_root` raises, the Workspace
        and its membership go back out. Making all three atomic is a
        cross-store question, and it belongs with #38 rather than here.
        """
        workspace = Workspace(name=name, description=description)
        owner = WorkspaceMembership(
            workspace_id=workspace.workspace_id,
            user_id=creator_user_id,
            role=WorkspaceRole.OWNER,
            added_at=workspace.created_at,
        )
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO canonical_workspaces
                       (workspace_id, name, created_at, updated_at, payload)
                   VALUES ($1, $2, $3, $4, $5)""",
                workspace.workspace_id,
                workspace.name,
                workspace.created_at,
                workspace.updated_at,
                json_of(workspace),
            )
            await self._insert_membership(conn, owner)

        try:
            await self.project_store.create_root(workspace.workspace_id)
        except BaseException:
            await self._purge(workspace.workspace_id)
            raise
        return workspace

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
                      SET name = $2, updated_at = $3, payload = $4
                    WHERE workspace_id = $1""",
                updated.workspace_id,
                updated.name,
                updated.updated_at,
                json_of(updated),
            )
        # `UPDATE 0` rather than a preceding SELECT: one round trip, and no
        # window in which the row is found and then gone.
        if status.endswith(" 0"):
            raise WorkspaceNotFound(workspace.workspace_id)
        return updated

    async def delete(self, workspace_id: str) -> None:
        async with self._pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM canonical_workspaces WHERE workspace_id = $1",
                workspace_id,
            )
        if status.endswith(" 0"):
            raise WorkspaceNotFound(workspace_id)
        # Memberships go with the Workspace by `ON DELETE CASCADE`. The Projects
        # do not: they are the other store's rows, and it owns how they go.
        purge = getattr(self.project_store, "purge_workspace", None)
        if purge is not None:
            purge(workspace_id)

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT w.payload
                     FROM canonical_workspaces w
                     JOIN canonical_workspace_memberships m
                       ON m.workspace_id = w.workspace_id
                    WHERE m.user_id = $1
                    ORDER BY w.created_at DESC""",
                user_id,
            )
        return [model_of(Workspace, row["payload"]) for row in rows]

    async def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]:
        async with self._pool.acquire() as conn:
            await self._require_workspace(conn, workspace_id)
            rows = await conn.fetch(
                """SELECT payload FROM canonical_workspace_memberships
                    WHERE workspace_id = $1
                    ORDER BY added_at, user_id""",
                workspace_id,
            )
        return [model_of(WorkspaceMembership, row["payload"]) for row in rows]

    async def get_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
    ) -> WorkspaceMembership | None:
        async with self._pool.acquire() as conn:
            await self._require_workspace(conn, workspace_id)
            payload = await conn.fetchval(
                """SELECT payload FROM canonical_workspace_memberships
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
            existing_payload = await conn.fetchval(
                """SELECT payload FROM canonical_workspace_memberships
                    WHERE workspace_id = $1 AND user_id = $2""",
                workspace_id,
                user_id,
            )
            existing = (
                model_of(WorkspaceMembership, existing_payload)
                if existing_payload is not None
                else None
            )
            if (
                existing is not None
                and existing.role is WorkspaceRole.OWNER
                and role is not WorkspaceRole.OWNER
            ):
                await self._require_another_owner(conn, workspace_id, excluding_user_id=user_id)

            membership = WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=user_id,
                role=role,
                added_at=existing.added_at if existing is not None else datetime.now(UTC),
            )
            await self._insert_membership(conn, membership, on_conflict_update=True)
        return membership

    async def remove_membership(self, workspace_id: str, *, user_id: str) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await self._lock_workspace(conn, workspace_id)
            role = await conn.fetchval(
                """SELECT role FROM canonical_workspace_memberships
                    WHERE workspace_id = $1 AND user_id = $2""",
                workspace_id,
                user_id,
            )
            if role is None:
                return
            if role == WorkspaceRole.OWNER.value:
                await self._require_another_owner(conn, workspace_id, excluding_user_id=user_id)
            await conn.execute(
                """DELETE FROM canonical_workspace_memberships
                    WHERE workspace_id = $1 AND user_id = $2""",
                workspace_id,
                user_id,
            )

    async def _insert_membership(
        self,
        conn: Any,
        membership: WorkspaceMembership,
        *,
        on_conflict_update: bool = False,
    ) -> None:
        conflict = (
            """ON CONFLICT (workspace_id, user_id) DO UPDATE
                   SET role = EXCLUDED.role,
                       added_at = EXCLUDED.added_at,
                       payload = EXCLUDED.payload"""
            if on_conflict_update
            else ""
        )
        await conn.execute(
            f"""INSERT INTO canonical_workspace_memberships
                    (workspace_id, user_id, role, added_at, payload)
                VALUES ($1, $2, $3, $4, $5)
                {conflict}""",
            membership.workspace_id,
            membership.user_id,
            membership.role.value,
            membership.added_at,
            json_of(membership),
        )

    async def _lock_workspace(self, conn: Any, workspace_id: str) -> None:
        """Serialise membership writes for one Workspace, or refuse.

        `FOR UPDATE` on the Workspace row rather than on the membership rows:
        the rule is about how many owner rows exist, so the thing that has to
        be serialised is the *set*, and the parent row is the only object every
        writer for this Workspace touches.
        """
        locked = await conn.fetchval(
            "SELECT workspace_id FROM canonical_workspaces WHERE workspace_id = $1 FOR UPDATE",
            workspace_id,
        )
        if locked is None:
            raise WorkspaceNotFound(workspace_id)

    async def _require_workspace(self, conn: Any, workspace_id: str) -> None:
        exists = await conn.fetchval(
            "SELECT 1 FROM canonical_workspaces WHERE workspace_id = $1",
            workspace_id,
        )
        if exists is None:
            raise WorkspaceNotFound(workspace_id)

    async def _require_another_owner(
        self, conn: Any, workspace_id: str, *, excluding_user_id: str
    ) -> None:
        other_owner = await conn.fetchval(
            """SELECT 1 FROM canonical_workspace_memberships
                WHERE workspace_id = $1 AND user_id <> $2 AND role = $3
                LIMIT 1""",
            workspace_id,
            excluding_user_id,
            WorkspaceRole.OWNER.value,
        )
        if other_owner is None:
            raise WorkspaceAccessDenied("a Workspace must retain at least one owner")

    async def _purge(self, workspace_id: str) -> None:
        """Undo `create`'s rows after the Root Project failed.

        Deliberately quiet about a Workspace that is already gone: this runs on
        the failure path, and raising here would replace the error the caller
        needs to see with one about the cleanup.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM canonical_workspaces WHERE workspace_id = $1",
                workspace_id,
            )


__all__ = ["PgWorkspaceStore"]
