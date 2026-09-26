"""SQLite persistence for Workspace BacklogItems (#98).

Held to the in-memory reference by one conformance suite. The rules that need
a read before the write -- the Project belongs to the item's Workspace, an edge
stays inside one Workspace and closes no cycle, the stored version is still
the expected one -- run inside the paired `SqliteProjectScopeStore`'s
`transaction()`: its lock and its `BEGIN IMMEDIATE` on the one shared
connection, the `SqliteWorkspaceStore` precedent (#1121). A lock of this
store's own over that connection is how "cannot start a transaction within a
transaction" happens. The version check is also the `UPDATE`'s own `WHERE`, so
it holds even against a second process on the same file.

The payload JSON is the record; the other columns exist to be queried, and
timestamps are ISO-8601 text as in the Workspace store.
"""

from __future__ import annotations

import builtins
import sqlite3
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.projects.scope_store import DurableProjectScopeStore, TransactionalProjectScopeStore
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade
from maistro.workspaces.backlog.model import (
    BacklogItem,
    BacklogItemAlreadyExists,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogRelationError,
    BacklogVersionConflict,
    apply_changes,
    new_item,
)
from maistro.workspaces.backlog.store import (
    require_not_self,
    require_project_in_workspace,
    require_same_workspace,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

    from maistro.projects.scope_store import ProjectScopeStore

# No FK to canonical_projects yet: Project deletion does not know about
# BacklogItems, and a RESTRICT it cannot explain is a later slice's call.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_backlog_items (
    item_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    external_key TEXT,
    status TEXT NOT NULL,
    parent_item_id TEXT,
    rank REAL NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workspace_backlog_items_workspace
    ON workspace_backlog_items(workspace_id, rank, created_at, item_id);
CREATE INDEX IF NOT EXISTS idx_workspace_backlog_items_parent
    ON workspace_backlog_items(parent_item_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_backlog_items_external_key
    ON workspace_backlog_items(workspace_id, external_key)
    WHERE external_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS workspace_backlog_dependencies (
    item_id TEXT NOT NULL REFERENCES workspace_backlog_items(item_id) ON DELETE CASCADE,
    depends_on_item_id TEXT NOT NULL
        REFERENCES workspace_backlog_items(item_id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, depends_on_item_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_backlog_dependencies_target
    ON workspace_backlog_dependencies(depends_on_item_id);
"""

_GET = "SELECT payload FROM workspace_backlog_items WHERE item_id = ?"

_LIST = """
SELECT payload FROM workspace_backlog_items
 WHERE workspace_id = ?
   AND (? IS NULL OR project_id = ?)
   AND (? IS NULL OR status = ?)
 ORDER BY rank, created_at, item_id
"""

_CHILDREN = """
SELECT payload FROM workspace_backlog_items
 WHERE parent_item_id = ?
 ORDER BY rank, created_at, item_id
"""

_DEPENDENCIES = """
SELECT i.payload FROM workspace_backlog_items i
  JOIN workspace_backlog_dependencies d ON d.depends_on_item_id = i.item_id
 WHERE d.item_id = ?
 ORDER BY i.rank, i.created_at, i.item_id
"""

_DEPENDENTS = """
SELECT i.payload FROM workspace_backlog_items i
  JOIN workspace_backlog_dependencies d ON d.item_id = i.item_id
 WHERE d.depends_on_item_id = ?
 ORDER BY i.rank, i.created_at, i.item_id
"""

_REACHES_BY_DEPENDENCY = """
WITH RECURSIVE reach(id) AS (
    SELECT ?
    UNION
    SELECT d.depends_on_item_id
      FROM workspace_backlog_dependencies d JOIN reach r ON d.item_id = r.id
)
SELECT 1 FROM reach WHERE id = ? LIMIT 1
"""

_REACHES_BY_PARENT = """
WITH RECURSIVE up(id) AS (
    SELECT ?
    UNION
    SELECT i.parent_item_id
      FROM workspace_backlog_items i JOIN up ON i.item_id = up.id
     WHERE i.parent_item_id IS NOT NULL
)
SELECT 1 FROM up WHERE id = ? LIMIT 1
"""


class SqliteBacklogItemStore:
    """Durable BacklogItems for a single instance."""

    def __init__(self, conn: aiosqlite.Connection, *, project_store: ProjectScopeStore) -> None:
        if not isinstance(project_store, TransactionalProjectScopeStore):
            msg = (
                "SqliteBacklogItemStore writes inside its Project store's transaction; "
                f"{type(project_store).__name__} has none. Pair it with "
                "SqliteProjectScopeStore on the same connection."
            )
            raise TypeError(msg)
        self._conn = conn
        self._project_store: DurableProjectScopeStore = project_store

    async def ensure_schema(self) -> None:
        await self._conn.execute("PRAGMA foreign_keys = ON")
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SCHEMA)

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._project_store.transaction() as conn:
            yield conn

    async def create(self, item: BacklogItem) -> BacklogItem:
        created = new_item(item)
        async with self._write() as conn:
            await require_project_in_workspace(
                self._project_store, created.project_id, created.workspace_id
            )
            if created.parent_item_id is not None:
                require_same_workspace(created, await self._require(created.parent_item_id))
            try:
                await conn.execute(
                    """INSERT INTO workspace_backlog_items
                           (item_id, workspace_id, project_id, external_key, status,
                            parent_item_id, rank, version, updated_at, created_at, payload)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        created.item_id,
                        created.workspace_id,
                        *_mutable_columns(created),
                        _iso(created.created_at),
                        created.model_dump_json(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise BacklogItemAlreadyExists(created.item_id) from exc
        return created

    async def get(self, item_id: str) -> BacklogItem | None:
        rows = await self._select(_GET, (item_id,))
        return rows[0] if rows else None

    async def list(
        self,
        workspace_id: str,
        project_id: str | None = None,
        status: BacklogItemStatus | None = None,
    ) -> builtins.list[BacklogItem]:
        status_value = None if status is None else BacklogItemStatus(status).value
        return await self._select(
            _LIST, (workspace_id, project_id, project_id, status_value, status_value)
        )

    async def update(
        self, item_id: str, *, expected_version: int, changes: Mapping[str, Any]
    ) -> BacklogItem:
        async with self._write() as conn:
            current = await self._current(item_id, expected_version)
            updated = apply_changes(current, dict(changes))
            if updated.project_id != current.project_id:
                await require_project_in_workspace(
                    self._project_store, updated.project_id, updated.workspace_id
                )
            await self._compare_and_set(conn, updated, expected_version)
        return updated

    async def add_dependency(self, item_id: str, depends_on_item_id: str) -> None:
        async with self._write() as conn:
            item = await self._require(item_id)
            other = await self._require(depends_on_item_id)
            require_not_self(item_id, depends_on_item_id)
            require_same_workspace(item, other)
            if await self._exists(_REACHES_BY_DEPENDENCY, (depends_on_item_id, item_id)):
                raise BacklogRelationError(
                    "cycle", f"{item_id} -> {depends_on_item_id} closes a dependency cycle"
                )
            await conn.execute(
                """INSERT OR IGNORE INTO workspace_backlog_dependencies
                       (item_id, depends_on_item_id) VALUES (?, ?)""",
                (item_id, depends_on_item_id),
            )

    async def remove_dependency(self, item_id: str, depends_on_item_id: str) -> None:
        async with self._write() as conn:
            await self._require(item_id)
            await conn.execute(
                """DELETE FROM workspace_backlog_dependencies
                    WHERE item_id = ? AND depends_on_item_id = ?""",
                (item_id, depends_on_item_id),
            )

    async def dependencies_of(self, item_id: str) -> builtins.list[BacklogItem]:
        await self._require(item_id)
        return await self._select(_DEPENDENCIES, (item_id,))

    async def dependents_of(self, item_id: str) -> builtins.list[BacklogItem]:
        await self._require(item_id)
        return await self._select(_DEPENDENTS, (item_id,))

    async def children_of(self, item_id: str) -> builtins.list[BacklogItem]:
        await self._require(item_id)
        return await self._select(_CHILDREN, (item_id,))

    async def set_parent(
        self, item_id: str, parent_item_id: str | None, *, expected_version: int
    ) -> BacklogItem:
        async with self._write() as conn:
            current = await self._require(item_id)
            if parent_item_id is not None:
                require_not_self(item_id, parent_item_id)
                require_same_workspace(current, await self._require(parent_item_id))
                if await self._exists(_REACHES_BY_PARENT, (parent_item_id, item_id)):
                    raise BacklogRelationError(
                        "cycle", f"{parent_item_id} is a descendant of {item_id}"
                    )
            current = await self._current(item_id, expected_version)
            updated = apply_changes(current, {}).model_copy(
                update={"parent_item_id": parent_item_id}
            )
            await self._compare_and_set(conn, updated, expected_version)
        return updated

    async def _compare_and_set(
        self, conn: aiosqlite.Connection, updated: BacklogItem, expected_version: int
    ) -> None:
        try:
            cursor = await conn.execute(
                """UPDATE workspace_backlog_items
                      SET project_id = ?, external_key = ?, status = ?, parent_item_id = ?,
                          rank = ?, version = ?, updated_at = ?, payload = ?
                    WHERE item_id = ? AND version = ?""",
                (
                    *_mutable_columns(updated),
                    updated.model_dump_json(),
                    updated.item_id,
                    expected_version,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise BacklogItemAlreadyExists(updated.external_key or updated.item_id) from exc
        if cursor.rowcount == 0:
            raise BacklogVersionConflict(expected_version, await self._require(updated.item_id))

    async def _current(self, item_id: str, expected_version: int) -> BacklogItem:
        current = await self._require(item_id)
        if current.version != expected_version:
            raise BacklogVersionConflict(expected_version, current)
        return current

    async def _require(self, item_id: str) -> BacklogItem:
        item = await self.get(item_id)
        if item is None:
            raise BacklogItemNotFound(item_id)
        return item

    async def _select(self, sql: str, params: tuple[Any, ...]) -> builtins.list[BacklogItem]:
        async with self._conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [BacklogItem.model_validate_json(row[0]) for row in rows]

    async def _exists(self, sql: str, params: tuple[str, ...]) -> bool:
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone() is not None


def _mutable_columns(item: BacklogItem) -> tuple[Any, ...]:
    return (
        item.project_id,
        item.external_key,
        item.status.value,
        item.parent_item_id,
        item.rank,
        item.version,
        _iso(item.updated_at),
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


__all__ = ["SqliteBacklogItemStore"]
