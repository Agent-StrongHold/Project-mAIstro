"""SQLite GraphTemplate registry (#145).

The homelab twin of `PgGraphTemplateStore`. Every other store in this codebase
comes in all three backends, and a registry that existed only in memory and in
PostgreSQL would mean a SQLite deployment silently lost its templates on
restart — with the schedules that name them still pointing at nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.graph.definitions import GraphTemplate, NodeTemplate
from maistro.graph.templates import GraphTemplateConflict, NodeTemplateConflict, revalidated

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_templates (
    template_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (template_id, version)
);

CREATE INDEX IF NOT EXISTS idx_graph_templates_workspace
    ON graph_templates (workspace_id, name);
"""

_NODE_SCHEMA = """
CREATE TABLE IF NOT EXISTS node_templates (
    template_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    node_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (template_id, version)
);

CREATE INDEX IF NOT EXISTS idx_node_templates_workspace
    ON node_templates (workspace_id, name);
"""


class SqliteGraphTemplateStore:
    """Durable registry resolving `graph_template_id` to a GraphTemplate."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def put(self, template: GraphTemplate) -> GraphTemplate:
        """Register one version, idempotently for identical content.

        Read-then-write rather than an upsert with a predicate: SQLite has
        `ON CONFLICT DO UPDATE ... WHERE`, but this store shares one serialised
        connection, so the check cannot race the way it could on PostgreSQL and
        the simpler form is the honest one.
        """
        cursor = await self._conn.execute(
            "SELECT content_hash FROM graph_templates WHERE template_id = ? AND version = ?",
            (template.template_id, template.version),
        )
        row = await cursor.fetchone()
        if row is not None and row[0] != template.content_hash:
            raise GraphTemplateConflict(
                f"GraphTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
            )
        await self._conn.execute(
            """INSERT OR REPLACE INTO graph_templates
                   (template_id, version, workspace_id, name, content_hash, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                template.template_id,
                template.version,
                template.workspace_id,
                template.name,
                template.content_hash,
                revalidated(template).model_dump_json(),
            ),
        )
        await self._conn.commit()
        return template

    async def get(self, template_id: str, *, version: int | None = None) -> GraphTemplate | None:
        if version is not None:
            cursor = await self._conn.execute(
                "SELECT payload FROM graph_templates WHERE template_id = ? AND version = ?",
                (template_id, version),
            )
        else:
            cursor = await self._conn.execute(
                """SELECT payload FROM graph_templates
                   WHERE template_id = ?
                   ORDER BY version DESC
                   LIMIT 1""",
                (template_id,),
            )
        row = await cursor.fetchone()
        return GraphTemplate.model_validate_json(row[0]) if row is not None else None

    async def list_for_workspace(self, workspace_id: str) -> list[GraphTemplate]:
        cursor = await self._conn.execute(
            """SELECT payload FROM graph_templates
               WHERE workspace_id = ?
               ORDER BY name, template_id, version""",
            (workspace_id,),
        )
        return [GraphTemplate.model_validate_json(row[0]) for row in await cursor.fetchall()]

    async def versions(self, template_id: str) -> list[int]:
        cursor = await self._conn.execute(
            "SELECT version FROM graph_templates WHERE template_id = ? ORDER BY version",
            (template_id,),
        )
        return [int(row[0]) for row in await cursor.fetchall()]


class SqliteNodeTemplateStore:
    """Durable NodeTemplate registry for a SQLite deployment (#556).

    Present for the reason its GraphTemplate sibling is: every other store in
    this codebase comes in all three backends, and a registry that existed only
    in memory and in PostgreSQL would mean a homelab deployment silently lost
    its NodeTemplates on restart -- with every Node that cites one still
    recording provenance for a template nothing can resolve.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_NODE_SCHEMA)
        await self._conn.commit()

    async def put(self, template: NodeTemplate) -> NodeTemplate:
        """Register one version, idempotently for identical content.

        Read-then-write, as the GraphTemplate twin does and for the same
        reason: this store shares one serialised connection, so the check
        cannot race the way it could on PostgreSQL.
        """
        cursor = await self._conn.execute(
            "SELECT content_hash FROM node_templates WHERE template_id = ? AND version = ?",
            (template.template_id, template.version),
        )
        row = await cursor.fetchone()
        if row is not None and row[0] != template.content_hash:
            raise NodeTemplateConflict(
                f"NodeTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
            )
        await self._conn.execute(
            """INSERT OR REPLACE INTO node_templates
                   (template_id, version, workspace_id, name, node_type, content_hash, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                template.template_id,
                template.version,
                template.workspace_id,
                template.name,
                template.node_type,
                template.content_hash,
                revalidated(template).model_dump_json(),
            ),
        )
        await self._conn.commit()
        return template

    async def get(self, template_id: str, *, version: int | None = None) -> NodeTemplate | None:
        if version is not None:
            cursor = await self._conn.execute(
                "SELECT payload FROM node_templates WHERE template_id = ? AND version = ?",
                (template_id, version),
            )
        else:
            cursor = await self._conn.execute(
                """SELECT payload FROM node_templates
                   WHERE template_id = ?
                   ORDER BY version DESC
                   LIMIT 1""",
                (template_id,),
            )
        row = await cursor.fetchone()
        return NodeTemplate.model_validate_json(row[0]) if row is not None else None

    async def list_for_workspace(self, workspace_id: str) -> list[NodeTemplate]:
        cursor = await self._conn.execute(
            """SELECT payload FROM node_templates
               WHERE workspace_id = ?
               ORDER BY name, template_id, version""",
            (workspace_id,),
        )
        return [NodeTemplate.model_validate_json(row[0]) for row in await cursor.fetchall()]

    async def versions(self, template_id: str) -> list[int]:
        cursor = await self._conn.execute(
            "SELECT version FROM node_templates WHERE template_id = ? ORDER BY version",
            (template_id,),
        )
        return [int(row[0]) for row in await cursor.fetchall()]


__all__ = ["SqliteGraphTemplateStore", "SqliteNodeTemplateStore"]
