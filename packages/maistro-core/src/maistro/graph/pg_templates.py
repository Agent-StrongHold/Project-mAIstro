"""PostgreSQL GraphTemplate registry (#145).

The durable twin of `InMemoryGraphTemplateStore`. Same identity —
`(template_id, version)` — and the same refusal to redefine an existing version
with different content, except that here the refusal is a primary key plus a
content-hash comparison inside one statement rather than a check followed by a
write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.graph.definitions import GraphTemplate
from maistro.graph.templates import GraphTemplateConflict

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg


class PgGraphTemplateStore:
    """Durable registry resolving `graph_template_id` to a GraphTemplate."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def put(self, template: GraphTemplate) -> GraphTemplate:
        """Register one version, idempotently for identical content.

        `DO UPDATE ... WHERE` rather than `DO NOTHING`: on conflict this has to
        distinguish "already registered, same content" from "already registered,
        different content", and `DO NOTHING` returns no row either way. The
        predicate makes the update a no-op for a matching hash and skips it
        otherwise, so an empty result means exactly one thing — a redefinition.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO graph_templates
                       (template_id, version, workspace_id, name, content_hash, payload)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (template_id, version) DO UPDATE
                       SET payload = EXCLUDED.payload
                       WHERE graph_templates.content_hash = EXCLUDED.content_hash
                   RETURNING template_id""",
                template.template_id,
                template.version,
                template.workspace_id,
                template.name,
                template.content_hash,
                template.model_dump(mode="json"),
            )
        if row is None:
            raise GraphTemplateConflict(
                f"GraphTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
            )
        return template

    async def get(self, template_id: str, *, version: int | None = None) -> GraphTemplate | None:
        async with self._pool.acquire() as conn:
            if version is not None:
                payload: Any = await conn.fetchval(
                    "SELECT payload FROM graph_templates WHERE template_id = $1 AND version = $2",
                    template_id,
                    version,
                )
            else:
                payload = await conn.fetchval(
                    """SELECT payload FROM graph_templates
                       WHERE template_id = $1
                       ORDER BY version DESC
                       LIMIT 1""",
                    template_id,
                )
        return GraphTemplate.model_validate(payload) if payload is not None else None

    async def list_for_workspace(self, workspace_id: str) -> list[GraphTemplate]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload FROM graph_templates
                   WHERE workspace_id = $1
                   ORDER BY name, template_id, version""",
                workspace_id,
            )
        return [GraphTemplate.model_validate(row["payload"]) for row in rows]

    async def versions(self, template_id: str) -> list[int]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT version FROM graph_templates WHERE template_id = $1 ORDER BY version",
                template_id,
            )
        return [int(row["version"]) for row in rows]


__all__ = ["PgGraphTemplateStore"]
