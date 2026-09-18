"""SQLite persistence for the canonical Workspace (homelab/single-instance).

The same protocol and the same rules as `pg_store.py`, read against the same
conformance suite. Two things genuinely differ, and both are about what SQLite
already guarantees.

**Serialisation.** PostgreSQL needs an explicit `SELECT ... FOR UPDATE` to make
"a Workspace must retain at least one owner" atomic, because two connections
can read the roster concurrently. SQLite allows one writer at a time, so a
`BEGIN IMMEDIATE` around the read-then-write is the whole of it — the write
lock is taken before the roster is read, and a second writer waits rather than
reading a roster that is about to change.

**Timestamps.** SQLite has no timestamp type; a `datetime` stored through
aiosqlite comes back as text, and a naive one comes back indistinguishable from
an aware one. Both stores must return timezone-aware UTC, because the reference
builds them with `datetime.now(UTC)` and a naive value compares unequal to what
was written. So ordering columns are stored as ISO-8601 text — which sorts
correctly for UTC — and the values callers actually read come back from the
JSON payload, where pydantic restores the offset.

**One connection, one lock, one transaction (#1121).** This store and the
SQLite Project scope store write on the same aiosqlite connection, and a
Workspace is rows in both: the Workspace, its owner membership, and its Root
Project. They used to be written as commit-then-`create_root`, with an
in-process compensator for an exception between the two and nothing for a
crash there; `delete` was the same in reverse. Now, when the paired Project
store is a `TransactionalProjectScopeStore` (the SQLite one is), every write
here takes *its* `transaction()` -- its `asyncio.Lock`, its `BEGIN IMMEDIATE`,
its commit or rollback -- and `create`/`delete` issue `create_root_in` /
`purge_workspace_in` inside that same block. The lock has to be the scope
store's rather than one of this store's own: two locks over one connection
let two `BEGIN IMMEDIATE`s interleave, which SQLite reports as "cannot start a
transaction within a transaction". A Project store that cannot join a
transaction is refused at construction: the wiring never pairs one with this
store, and a compensating path that is not crash-consistent by construction
would be dead code carrying a promise it cannot keep.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict

from maistro.projects.scope_store import TransactionalProjectScopeStore
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade
from maistro.workspaces.model import (
    Workspace,
    WorkspaceAccessDenied,
    WorkspaceMembership,
    WorkspaceNotFound,
    WorkspaceRole,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

    from maistro.projects.scope_store import ProjectScopeStore


class _WorkspaceCreateKwargs(TypedDict):
    name: str
    description: str
    workspace_id: NotRequired[str]
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS canonical_workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_canonical_workspaces_created
    ON canonical_workspaces(created_at);

CREATE TABLE IF NOT EXISTS canonical_workspace_memberships (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    added_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (workspace_id, user_id),
    FOREIGN KEY (workspace_id) REFERENCES canonical_workspaces(workspace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_canonical_workspace_memberships_user
    ON canonical_workspace_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_canonical_workspace_memberships_owner
    ON canonical_workspace_memberships(workspace_id)
    WHERE role = 'owner';
"""


class SqliteWorkspaceStore:
    """Durable Workspace identity and membership store for a single instance."""

    def __init__(self, conn: aiosqlite.Connection, *, project_store: ProjectScopeStore) -> None:
        if not isinstance(project_store, TransactionalProjectScopeStore):
            msg = (
                "SqliteWorkspaceStore needs a Project store that can join its transaction "
                f"(#1121); {type(project_store).__name__} cannot. Pair it with "
                "SqliteProjectScopeStore on the same connection."
            )
            raise TypeError(msg)
        self._conn = conn
        self.project_store: TransactionalProjectScopeStore = project_store

    async def ensure_schema(self) -> None:
        """Create the Workspace tables and their indexes."""
        await self._conn.execute("PRAGMA foreign_keys = ON")
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SCHEMA)

    @asynccontextmanager
    async def _write_transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """The one write-critical section this connection has: the Project
        store's, because the connection is shared and a second lock over it
        is the "cannot start a transaction within a transaction" failure
        (#1121)."""
        async with self.project_store.transaction() as conn:
            yield conn

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
        workspace_kwargs: _WorkspaceCreateKwargs = {"name": name, "description": description}
        if workspace_id is not None:
            workspace_kwargs["workspace_id"] = workspace_id
        if created_at is not None:
            workspace_kwargs["created_at"] = created_at
        if updated_at is not None:
            workspace_kwargs["updated_at"] = updated_at
        workspace = Workspace(**workspace_kwargs)
        owner = WorkspaceMembership(
            workspace_id=workspace.workspace_id,
            user_id=creator_user_id,
            role=WorkspaceRole.OWNER,
            added_at=workspace.created_at,
        )
        # One `BEGIN IMMEDIATE` ... `COMMIT` for all three rows (#1121). The
        # Root Project is written last, inside the block, so a failure
        # anywhere rolls the Workspace and membership back with it.
        async with self._write_transaction() as conn:
            await self._insert_workspace(workspace)
            await self._write_membership(owner)
            await self.project_store.create_root_in(conn, workspace.workspace_id)
        return workspace

    async def get(self, workspace_id: str) -> Workspace | None:
        """Return the Workspace, or ``None`` when no record has that id."""
        async with self._conn.execute(
            "SELECT payload FROM canonical_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return Workspace.model_validate_json(row[0]) if row is not None else None

    async def update(self, workspace: Workspace) -> Workspace:
        """Persist a changed Workspace and stamp ``updated_at``."""
        updated = workspace.model_copy(update={"updated_at": datetime.now(UTC)})
        async with self._write_transaction() as conn:
            cursor = await conn.execute(
                """UPDATE canonical_workspaces
                      SET name = ?, updated_at = ?, payload = ?
                    WHERE workspace_id = ?""",
                (
                    updated.name,
                    _iso(updated.updated_at),
                    updated.model_dump_json(),
                    updated.workspace_id,
                ),
            )
            if cursor.rowcount == 0:
                raise WorkspaceNotFound(workspace.workspace_id)
        return updated

    async def delete(self, workspace_id: str) -> None:
        """Remove the Workspace, its memberships, and its Projects."""
        # Purge first, then the Workspace row, in one transaction (#1121).
        # `WorkspaceNotFound` from the row delete rolls the purge back with
        # it, so deleting an absent Workspace touches nothing.
        async with self._write_transaction() as conn:
            await self.project_store.purge_workspace_in(conn, workspace_id)
            await self._delete_workspace_row(conn, workspace_id)

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        """Workspaces the user is a member of, newest first."""
        async with self._conn.execute(
            """SELECT w.payload
                 FROM canonical_workspaces w
                 JOIN canonical_workspace_memberships m
                   ON m.workspace_id = w.workspace_id
                WHERE m.user_id = ?
                ORDER BY w.created_at DESC""",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Workspace.model_validate_json(row[0]) for row in rows]

    async def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]:
        """Every membership in the Workspace, ordered by (added_at, user_id)."""
        await self._require_workspace(workspace_id)
        async with self._conn.execute(
            """SELECT payload FROM canonical_workspace_memberships
                WHERE workspace_id = ?
                ORDER BY added_at, user_id""",
            (workspace_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [WorkspaceMembership.model_validate_json(row[0]) for row in rows]

    async def get_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
    ) -> WorkspaceMembership | None:
        """One user's membership, or ``None`` when they are not a member."""
        await self._require_workspace(workspace_id)
        async with self._conn.execute(
            """SELECT payload FROM canonical_workspace_memberships
                WHERE workspace_id = ? AND user_id = ?""",
            (workspace_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        return WorkspaceMembership.model_validate_json(row[0]) if row is not None else None

    async def set_membership(
        self,
        workspace_id: str,
        *,
        user_id: str,
        role: WorkspaceRole,
    ) -> WorkspaceMembership:
        """Create or re-role a membership, refusing to strip the last owner.

        The roster is read inside `BEGIN IMMEDIATE`, so the write lock is
        taken before the owner count is asked, not after.
        """
        async with self._write_transaction():
            await self._require_workspace(workspace_id)
            existing = await self._membership(workspace_id, user_id)
            if (
                existing is not None
                and existing.role is WorkspaceRole.OWNER
                and role is not WorkspaceRole.OWNER
            ):
                await self._require_another_owner(workspace_id, excluding_user_id=user_id)

            membership = WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=user_id,
                role=role,
                added_at=existing.added_at if existing is not None else datetime.now(UTC),
            )
            await self._write_membership(membership)
        return membership

    async def remove_membership(self, workspace_id: str, *, user_id: str) -> None:
        """Drop a membership, refusing to strip the last owner."""
        async with self._write_transaction() as conn:
            await self._require_workspace(workspace_id)
            existing = await self._membership(workspace_id, user_id)
            if existing is None:
                return
            if existing.role is WorkspaceRole.OWNER:
                await self._require_another_owner(workspace_id, excluding_user_id=user_id)
            await conn.execute(
                """DELETE FROM canonical_workspace_memberships
                    WHERE workspace_id = ? AND user_id = ?""",
                (workspace_id, user_id),
            )

    async def _insert_workspace(self, workspace: Workspace) -> None:
        await self._conn.execute(
            """INSERT INTO canonical_workspaces
                   (workspace_id, name, created_at, updated_at, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (
                workspace.workspace_id,
                workspace.name,
                _iso(workspace.created_at),
                _iso(workspace.updated_at),
                workspace.model_dump_json(),
            ),
        )

    async def _delete_workspace_row(self, conn: aiosqlite.Connection, workspace_id: str) -> None:
        """Delete the Workspace row (memberships cascade), or refuse."""
        cursor = await conn.execute(
            "DELETE FROM canonical_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        )
        if cursor.rowcount == 0:
            raise WorkspaceNotFound(workspace_id)

    async def _write_membership(self, membership: WorkspaceMembership) -> None:
        await self._conn.execute(
            """INSERT INTO canonical_workspace_memberships
                   (workspace_id, user_id, role, added_at, payload)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (workspace_id, user_id) DO UPDATE
                   SET role = excluded.role,
                       added_at = excluded.added_at,
                       payload = excluded.payload""",
            (
                membership.workspace_id,
                membership.user_id,
                membership.role.value,
                _iso(membership.added_at),
                membership.model_dump_json(),
            ),
        )

    async def _membership(self, workspace_id: str, user_id: str) -> WorkspaceMembership | None:
        async with self._conn.execute(
            """SELECT payload FROM canonical_workspace_memberships
                WHERE workspace_id = ? AND user_id = ?""",
            (workspace_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        return WorkspaceMembership.model_validate_json(row[0]) if row is not None else None

    async def _require_workspace(self, workspace_id: str) -> None:
        async with self._conn.execute(
            "SELECT 1 FROM canonical_workspaces WHERE workspace_id = ?",
            (workspace_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise WorkspaceNotFound(workspace_id)

    async def _require_another_owner(self, workspace_id: str, *, excluding_user_id: str) -> None:
        async with self._conn.execute(
            """SELECT 1 FROM canonical_workspace_memberships
                WHERE workspace_id = ? AND user_id <> ? AND role = ?
                LIMIT 1""",
            (workspace_id, excluding_user_id, WorkspaceRole.OWNER.value),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise WorkspaceAccessDenied("a Workspace must retain at least one owner")


def _iso(value: datetime) -> str:
    """An ordering key that sorts the way the datetime does."""
    return value.astimezone(UTC).isoformat()


__all__ = ["SqliteWorkspaceStore"]
