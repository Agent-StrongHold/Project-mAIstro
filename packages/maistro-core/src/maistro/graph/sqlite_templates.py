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

        One conditional upsert. This used to be a read followed by a write,
        justified as "this store shares one serialised connection, so the check
        cannot race" -- which is not what a shared connection buys. `aiosqlite`
        serialises individual statements; a read-then-write pair spanning an
        `await` is two of them, and two coroutines publishing different content
        under one `(template_id, version)` could both see no row before either
        wrote. The second `INSERT OR REPLACE` then destroyed the first version
        silently, which is the one outcome this store exists to prevent
        (Codex, #563).

        See `SqliteNodeTemplateStore.put` for why the trailing `SELECT` is
        there: `changes()` cannot distinguish "the predicate rejected it" from
        "nothing needed changing".
        """
        content = revalidated(template).model_dump_json()
        await self._conn.execute(
            """INSERT INTO graph_templates
                   (template_id, version, workspace_id, name, content_hash, payload)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (template_id, version) DO UPDATE
                   SET workspace_id = excluded.workspace_id,
                       name         = excluded.name,
                       payload      = excluded.payload
                   WHERE graph_templates.content_hash = excluded.content_hash""",
            (
                template.template_id,
                template.version,
                template.workspace_id,
                template.name,
                template.content_hash,
                content,
            ),
        )
        cursor = await self._conn.execute(
            "SELECT content_hash FROM graph_templates WHERE template_id = ? AND version = ?",
            (template.template_id, template.version),
        )
        row = await cursor.fetchone()
        if row is None or row[0] != template.content_hash:
            await self._conn.rollback()
            raise GraphTemplateConflict(
                f"GraphTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
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

        **One conditional upsert, not a read followed by a write.** The check
        and the insert must be one decision: `aiosqlite` serialises individual
        statements, not a read-then-write pair spanning an `await`, so two
        coroutines publishing different content under the same
        `(template_id, version)` could both observe no row and the second
        `INSERT OR REPLACE` would silently overwrite the first -- destroying
        the immutable historical version this store exists to keep, and doing
        it without raising (Codex, #563).

        `ON CONFLICT DO UPDATE ... WHERE` makes the conflict decision inside
        one statement, exactly as the PostgreSQL twin does. `changes()` is 0
        when the predicate rejected the row, and a row already present with a
        matching hash is re-affirmed rather than skipped, so 0 means one thing:
        a redefinition. The `SELECT` afterwards distinguishes "no row changed
        because the content differs" from "no row changed because nothing
        needed changing", which the row count alone cannot say.

        The GraphTemplate twin carries the same defect and the same claim in
        its docstring; it is fixed here too rather than left as the older of
        two implementations of one rule.
        """
        content = revalidated(template).model_dump_json()
        await self._conn.execute(
            """INSERT INTO node_templates
                   (template_id, version, workspace_id, name, node_type, content_hash, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (template_id, version) DO UPDATE
                   SET workspace_id = excluded.workspace_id,
                       name         = excluded.name,
                       node_type    = excluded.node_type,
                       payload      = excluded.payload
                   WHERE node_templates.content_hash = excluded.content_hash""",
            (
                template.template_id,
                template.version,
                template.workspace_id,
                template.name,
                template.node_type,
                template.content_hash,
                content,
            ),
        )
        cursor = await self._conn.execute(
            "SELECT content_hash FROM node_templates WHERE template_id = ? AND version = ?",
            (template.template_id, template.version),
        )
        row = await cursor.fetchone()
        if row is None or row[0] != template.content_hash:
            await self._conn.rollback()
            raise NodeTemplateConflict(
                f"NodeTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
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
