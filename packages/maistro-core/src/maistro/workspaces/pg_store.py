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
from typing import TYPE_CHECKING, Any, Final, NotRequired, TypedDict, cast

from maistro.projects.scope import ProjectNotFound
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


class _WorkspaceCreateKwargs(TypedDict):
    name: str
    description: str
    workspace_id: NotRequired[str]
    created_at: NotRequired[datetime]
    updated_at: NotRequired[datetime]


class PgWorkspaceStore:
    """Durable Workspace identity and membership store.

    Workspace identity and its Root Project use a durable lifecycle journal.
    ``creating`` and ``deleting`` rows are hidden from canonical reads and
    retried by ``recover`` at startup, so a process boundary cannot expose
    either half as a usable Workspace.
    """

    _ACTIVE = "active"
    _CREATING = "creating"
    _DELETING = "deleting"

    def __init__(self, pool: asyncpg.Pool, *, project_store: ProjectScopeStore) -> None:
        self._pool = pool
        self.project_store: ProjectScopeStore = project_store
        configure_lifecycle = getattr(project_store, "set_workspace_lifecycle_reader", None)
        if configure_lifecycle is not None:
            configure_lifecycle(self._lifecycle_state)

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
        """Write the Workspace, its owner membership, and its Root Project.

        Ordinary callers omit the explicit identity/timestamps. Those values
        exist only for convergence imports so a durable legacy Workspace keeps
        both its canonical ID and chronology (#37).
        """
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
            # A normal exception still gets the old all-or-neither behaviour.
            # A host crash skips this compensator; the durable `creating` row
            # is then completed by `recover` on the next startup.
            try:
                await self.project_store.purge_workspace(workspace.workspace_id)
                await self._delete_workspace(workspace.workspace_id, self._CREATING)
            except BaseException:
                pass
            raise
        return workspace

    async def recover(self) -> None:
        """Complete or roll back lifecycle rows left by an interrupted process."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT workspace_id, state
                     FROM canonical_workspace_lifecycle
                    WHERE state <> $1
                    ORDER BY workspace_id""",
                self._ACTIVE,
            )
            active_rows = await conn.fetch(
                """SELECT w.workspace_id
                     FROM canonical_workspaces AS w
                     JOIN canonical_workspace_lifecycle AS l USING (workspace_id)
                    WHERE l.state = $1
                    ORDER BY w.workspace_id""",
                self._ACTIVE,
            )
        for row in rows:
            workspace_id = row["workspace_id"]
            if row["state"] == self._CREATING:
                await self.project_store.create_root(workspace_id)
                await self._set_state(workspace_id, self._ACTIVE)
            elif row["state"] == self._DELETING:
                await self.project_store.purge_workspace(workspace_id)
                await self._delete_workspace(workspace_id, self._DELETING)

        # Rows written before the journal migration are active by default. Do
        # not invent a replacement Root Project for one that is missing: roll
        # the orphaned Workspace back to neither identity instead.
        for row in active_rows:
            workspace_id = row["workspace_id"]
            try:
                await self.project_store.root_for_workspace(workspace_id)
            except ProjectNotFound:
                await self._set_state(workspace_id, self._DELETING)
                await self.project_store.purge_workspace(workspace_id)
                await self._delete_workspace(workspace_id, self._DELETING)

    async def _stage_workspace_create(
        self, workspace: Workspace, owner: WorkspaceMembership
    ) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO canonical_workspaces
                       (workspace_id, name, created_at, updated_at, payload)
                   VALUES ($1, $2, $3, $4, $5::text::jsonb)""",
                workspace.workspace_id,
                workspace.name,
                workspace.created_at,
                workspace.updated_at,
                json_of(workspace),
            )
            await conn.execute(
                """INSERT INTO canonical_workspace_lifecycle
                       (workspace_id, state)
                   VALUES ($1, $2)""",
                workspace.workspace_id,
                self._CREATING,
            )
            await self._insert_membership(conn, owner)

    async def _set_state(self, workspace_id: str, state: str) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            status = await conn.execute(
                """UPDATE canonical_workspace_lifecycle
                      SET state = $2, updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = $1""",
                workspace_id,
                state,
            )
        if status.endswith(" 0"):
            raise WorkspaceNotFound(workspace_id)

    async def _delete_workspace(self, workspace_id: str, state: str) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """DELETE FROM canonical_workspaces AS w
                    USING canonical_workspace_lifecycle AS l
                   WHERE w.workspace_id = $1
                     AND l.workspace_id = w.workspace_id
                     AND l.state = $2""",
                workspace_id,
                state,
            )

    async def get(self, workspace_id: str) -> Workspace | None:
        """Return the Workspace, or ``None`` when no record has that id."""
        async with self._pool.acquire() as conn:
            payload = await conn.fetchval(
                """SELECT w.payload
                     FROM canonical_workspaces AS w
                     JOIN canonical_workspace_lifecycle AS l USING (workspace_id)
                    WHERE w.workspace_id = $1 AND l.state = $2""",
                workspace_id,
                self._ACTIVE,
            )
        return model_of(Workspace, payload) if payload is not None else None

    async def update(self, workspace: Workspace) -> Workspace:
        """Persist a changed Workspace and stamp ``updated_at``."""
        updated = workspace.model_copy(update={"updated_at": datetime.now(UTC)})
        async with self._pool.acquire() as conn:
            status = await conn.execute(
                """UPDATE canonical_workspaces
                      SET name = $2, updated_at = $3, payload = $4::text::jsonb
                    WHERE workspace_id = $1
                      AND EXISTS (
                          SELECT 1 FROM canonical_workspace_lifecycle
                           WHERE workspace_id = $1 AND state = $5
                      )""",
                updated.workspace_id,
                updated.name,
                updated.updated_at,
                json_of(updated),
                self._ACTIVE,
            )
        if status.endswith(" 0"):
            raise WorkspaceNotFound(workspace.workspace_id)
        return updated

    async def delete(self, workspace_id: str) -> None:
        """Journal deletion before purging Projects, then remove both halves."""
        await self._set_state_if_active(workspace_id, self._DELETING)
        await self.project_store.purge_workspace(workspace_id)
        await self._delete_workspace(workspace_id, self._DELETING)

    async def _set_state_if_active(self, workspace_id: str, state: str) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await self._lock_workspace(conn, workspace_id)
            status = await conn.execute(
                """UPDATE canonical_workspace_lifecycle
                      SET state = $2, updated_at = CURRENT_TIMESTAMP
                    WHERE workspace_id = $1 AND state = $3""",
                workspace_id,
                state,
                self._ACTIVE,
            )
        if status.endswith(" 0"):
            raise WorkspaceNotFound(workspace_id)

    async def list_for_user(self, user_id: str) -> list[Workspace]:
        """Workspaces the user is a member of, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT w.payload
                     FROM canonical_workspaces w
                     JOIN canonical_workspace_memberships m
                       ON m.workspace_id = w.workspace_id
                     JOIN canonical_workspace_lifecycle l
                       ON l.workspace_id = w.workspace_id
                    WHERE m.user_id = $1 AND l.state = $2
                    ORDER BY w.created_at DESC""",
                user_id,
                self._ACTIVE,
            )
        return [model_of(Workspace, row["payload"]) for row in rows]

    async def list_memberships(self, workspace_id: str) -> list[WorkspaceMembership]:
        """Every membership in the Workspace, ordered by (added_at, user_id)."""
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
        """One user's membership, or ``None`` when they are not a member."""
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
        """Create or re-role a membership, refusing to strip the last owner."""
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
        """Drop a membership, refusing to strip the last owner."""
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

    _INSERT_MEMBERSHIP: Final = """
        INSERT INTO canonical_workspace_memberships
            (workspace_id, user_id, role, added_at, payload)
        VALUES ($1, $2, $3, $4, $5::text::jsonb)
    """
    _UPSERT_MEMBERSHIP: Final = """
        INSERT INTO canonical_workspace_memberships
            (workspace_id, user_id, role, added_at, payload)
        VALUES ($1, $2, $3, $4, $5::text::jsonb)
        ON CONFLICT (workspace_id, user_id) DO UPDATE
            SET role = EXCLUDED.role,
                added_at = EXCLUDED.added_at,
                payload = EXCLUDED.payload
    """

    async def _insert_membership(
        self,
        conn: Any,
        membership: WorkspaceMembership,
        *,
        on_conflict_update: bool = False,
    ) -> None:
        await conn.execute(
            self._UPSERT_MEMBERSHIP if on_conflict_update else self._INSERT_MEMBERSHIP,
            membership.workspace_id,
            membership.user_id,
            membership.role.value,
            membership.added_at,
            json_of(membership),
        )

    async def _lifecycle_state(self, workspace_id: str) -> str | None:
        async with self._pool.acquire() as conn:
            state = await conn.fetchval(
                """SELECT state FROM canonical_workspace_lifecycle
                    WHERE workspace_id = $1""",
                workspace_id,
            )
        return cast(str | None, state)

    async def _lock_workspace(self, conn: Any, workspace_id: str) -> None:
        """Serialise membership writes for one Workspace, or refuse."""
        locked = await conn.fetchval(
            """SELECT w.workspace_id
                 FROM canonical_workspaces AS w
                 JOIN canonical_workspace_lifecycle AS l USING (workspace_id)
                WHERE w.workspace_id = $1 AND l.state = $2
                FOR UPDATE OF w""",
            workspace_id,
            self._ACTIVE,
        )
        if locked is None:
            raise WorkspaceNotFound(workspace_id)

    async def _require_workspace(self, conn: Any, workspace_id: str) -> None:
        exists = await conn.fetchval(
            """SELECT 1
                 FROM canonical_workspaces AS w
                 JOIN canonical_workspace_lifecycle AS l USING (workspace_id)
                WHERE w.workspace_id = $1 AND l.state = $2""",
            workspace_id,
            self._ACTIVE,
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


__all__ = ["PgWorkspaceStore"]
