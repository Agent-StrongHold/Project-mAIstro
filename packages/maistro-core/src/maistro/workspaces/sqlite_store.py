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
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict

from maistro.projects.scope import ProjectNotFound
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

CREATE TABLE IF NOT EXISTS canonical_workspace_lifecycle (
    workspace_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('creating', 'active', 'deleting')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id) REFERENCES canonical_workspaces(workspace_id) ON DELETE CASCADE
);

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
    """Durable Workspace store with a crash-recoverable lifecycle journal."""

    _ACTIVE = "active"
    _CREATING = "creating"
    _DELETING = "deleting"

    def __init__(self, conn: aiosqlite.Connection, *, project_store: ProjectScopeStore) -> None:
        self._conn = conn
        self.project_store: ProjectScopeStore = project_store
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the Workspace tables and reconcile interrupted lifecycles."""
        await self._conn.executescript(_SCHEMA)
        await self._conn.execute(
            """INSERT OR IGNORE INTO canonical_workspace_lifecycle (workspace_id, state)
               SELECT workspace_id, 'active' FROM canonical_workspaces"""
        )
        await self._conn.commit()
        await self.recover()

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
        await self._stage_workspace_create(workspace, owner)
        try:
            await self.project_store.create_root(workspace.workspace_id)
            await self._set_state(workspace.workspace_id, self._ACTIVE)
        except BaseException:
            # A host crash skips this compensator; the durable `creating` row
            # is completed by `recover` on the next startup.
            try:
                await self.project_store.purge_workspace(workspace.workspace_id)
                await self._delete_workspace(workspace.workspace_id, self._CREATING)
            except BaseException:
                pass
            raise
        return workspace

    async def recover(self) -> None:
        """Complete or roll back lifecycle rows left by an interrupted process."""
        async with self._conn.execute(
            """SELECT workspace_id, state FROM canonical_workspace_lifecycle
                WHERE state <> ? ORDER BY workspace_id""",
            (self._ACTIVE,),
        ) as cursor:
            pending = await cursor.fetchall()
        async with self._conn.execute(
            """SELECT w.workspace_id
                 FROM canonical_workspaces AS w
                 JOIN canonical_workspace_lifecycle AS l USING (workspace_id)
                WHERE l.state = ? ORDER BY w.workspace_id""",
            (self._ACTIVE,),
        ) as cursor:
            active = await cursor.fetchall()

        for workspace_id, state in pending:
            if state == self._CREATING:
                await self.project_store.create_root(workspace_id)
                await self._set_state(workspace_id, self._ACTIVE)
            elif state == self._DELETING:
                await self.project_store.purge_workspace(workspace_id)
                await self._delete_workspace(workspace_id, self._DELETING)

        # Never silently mint a new Root Project for an already-visible orphan.
        # A pre-journal orphan is deterministically rolled back instead.
        for (workspace_id,) in active:
            try:
                await self.project_store.root_for_workspace(workspace_id)
            except ProjectNotFound:
                await self._set_state(workspace_id, self._DELETING)
                await self.project_store.purge_workspace(workspace_id)
                await self._delete_workspace(workspace_id, self._DELETING)

    async def _stage_workspace_create(
        self, workspace: Workspace, owner: WorkspaceMembership
    ) -> None:
        async with self._write_lock:
            await self._begin_immediate()
            try:
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
                await self._conn.execute(
                    """INSERT INTO canonical_workspace_lifecycle (workspace_id, state)
                       VALUES (?, ?)""",
                    (workspace.workspace_id, self._CREATING),
                )
                await self._write_membership(owner)
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

    async def _set_state(self, workspace_id: str, state: str) -> None:
        async with self._write_lock:
            await self._begin_immediate()
            try:
                cursor = await self._conn.execute(
                    """UPDATE canonical_workspace_lifecycle
                          SET state = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE workspace_id = ?""",
                    (state, workspace_id),
                )
                if cursor.rowcount == 0:
                    await self._conn.rollback()
                    raise WorkspaceNotFound(workspace_id)
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

    async def _delete_workspace(self, workspace_id: str, state: str) -> None:
        async with self._write_lock:
            await self._begin_immediate()
            try:
                await self._conn.execute(
                    """DELETE FROM canonical_workspaces
                        WHERE workspace_id = ?
                          AND workspace_id IN (
                              SELECT workspace_id FROM canonical_workspace_lifecycle
                               WHERE workspace_id = ? AND state = ?
                          )""",
                    (workspace_id, workspace_id, state),
                )
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

    async def get(self, workspace_id: str) -> Workspace | None:
        """Return the Workspace, or ``None`` when no record has that id."""
        async with self._conn.execute(
            """SELECT w.payload
                 FROM canonical_workspaces AS w
                 JOIN canonical_workspace_lifecycle AS l USING (workspace_id)
                WHERE w.workspace_id = ? AND l.state = ?""",
            (workspace_id, self._ACTIVE),
        ) as cursor:
            row = await cursor.fetchone()
        return Workspace.model_validate_json(row[0]) if row is not None else None

    async def update(self, workspace: Workspace) -> Workspace:
        """Persist a changed Workspace and stamp ``updated_at``."""
        updated = workspace.model_copy(update={"updated_at": datetime.now(UTC)})
        async with self._write_lock:
            await self._begin_immediate()
            try:
                cursor = await self._conn.execute(
                    """UPDATE canonical_workspaces
                          SET name = ?, updated_at = ?, payload = ?
                        WHERE workspace_id = ?
                          AND workspace_id IN (
                              SELECT workspace_id FROM canonical_workspace_lifecycle
                               WHERE workspace_id = ? AND state = ?
                          )""",
                    (
                        updated.name,
                        _iso(updated.updated_at),
                        updated.model_dump_json(),
                        updated.workspace_id,
                        updated.workspace_id,
                        self._ACTIVE,
                    ),
                )
                if cursor.rowcount == 0:
                    await self._conn.rollback()
                    raise WorkspaceNotFound(workspace.workspace_id)
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()
            return updated

    async def delete(self, workspace_id: str) -> None:
        """Journal deletion before purging Projects, then remove both halves."""
        await self._set_state_if_active(workspace_id, self._DELETING)
        await self.project_store.purge_workspace(workspace_id)
        await self._delete_workspace(workspace_id, self._DELETING)

    async def _set_state_if_active(self, workspace_id: str, state: str) -> None:
        async with self._write_lock:
            await self._begin_immediate()
            try:
                await self._require_workspace(workspace_id)
                cursor = await self._conn.execute(
                    """UPDATE canonical_workspace_lifecycle
                          SET state = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE workspace_id = ? AND state = ?""",
                    (state, workspace_id, self._ACTIVE),
                )
                if cursor.rowcount == 0:
                    await self._conn.rollback()
                    raise WorkspaceNotFound(workspace_id)
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        """Workspaces the user is a member of, newest first."""
        async with self._conn.execute(
            """SELECT w.payload
                 FROM canonical_workspaces w
                 JOIN canonical_workspace_memberships m
                   ON m.workspace_id = w.workspace_id
                JOIN canonical_workspace_lifecycle l
                   ON l.workspace_id = w.workspace_id
                WHERE m.user_id = ? AND l.state = ?
                ORDER BY w.created_at DESC""",
            (user_id, self._ACTIVE),
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
        """Create or re-role a membership, refusing to strip the last owner."""
        async with self._write_lock:
            await self._begin_immediate()
            try:
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
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()
            return membership

    async def remove_membership(self, workspace_id: str, *, user_id: str) -> None:
        """Drop a membership, refusing to strip the last owner."""
        async with self._write_lock:
            await self._begin_immediate()
            try:
                await self._require_workspace(workspace_id)
                existing = await self._membership(workspace_id, user_id)
                if existing is None:
                    await self._conn.rollback()
                    return
                if existing.role is WorkspaceRole.OWNER:
                    await self._require_another_owner(workspace_id, excluding_user_id=user_id)
                await self._conn.execute(
                    """DELETE FROM canonical_workspace_memberships
                        WHERE workspace_id = ? AND user_id = ?""",
                    (workspace_id, user_id),
                )
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

    async def _begin_immediate(self) -> None:
        """Take the write lock before reading the roster, not after."""
        await self._conn.execute("BEGIN IMMEDIATE")

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
            """SELECT 1
                 FROM canonical_workspaces AS w
                 JOIN canonical_workspace_lifecycle AS l USING (workspace_id)
                WHERE w.workspace_id = ? AND l.state = ?""",
            (workspace_id, self._ACTIVE),
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
