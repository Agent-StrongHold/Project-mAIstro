"""PostgreSQL GraphTemplate registry (#145).

The durable twin of `InMemoryGraphTemplateStore`. Same identity —
`(template_id, version)` — and the same refusal to redefine an existing version
with different content, except that here the refusal is a primary key plus a
content-hash comparison inside one statement rather than a check followed by a
write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.graph.definitions import GraphTemplate, NodeTemplate, TemplateLifecycle
from maistro.graph.templates import (
    GraphTemplateConflict,
    GraphTemplateNotFound,
    NodeTemplateConflict,
    NodeTemplateNotFound,
    revalidated,
)
from maistro.runs.evidence_json import json_of, model_of

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
                   VALUES ($1, $2, $3, $4, $5, $6::text::jsonb)
                   ON CONFLICT (template_id, version) DO UPDATE
                       SET workspace_id = EXCLUDED.workspace_id,
                           name         = EXCLUDED.name,
                           payload      = jsonb_set(
                                          EXCLUDED.payload,
                                          '{lifecycle}',
                                          COALESCE(graph_templates.payload->'lifecycle', '"active"'::jsonb),
                                          true
                                      )
                       WHERE graph_templates.content_hash = EXCLUDED.content_hash
                   RETURNING template_id""",
                template.template_id,
                template.version,
                template.workspace_id,
                template.name,
                template.content_hash,
                json_of(revalidated(template)),
            )
        if row is None:
            raise GraphTemplateConflict(
                f"GraphTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
            )
        return template

    async def set_lifecycle(
        self, template_id: str, version: int, lifecycle: TemplateLifecycle
    ) -> None:
        """The raw transition. `promote_audited` is the sanctioned path.

        `jsonb_set` rather than a rewritten payload: the lifecycle is the only
        thing moving, and rewriting the whole document to change one key would
        let an in-flight model change ride along with a promotion.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE graph_templates
                       SET payload = jsonb_set(payload, '{lifecycle}', to_jsonb($3::text), true)
                   WHERE template_id = $1 AND version = $2
                   RETURNING template_id""",
                template_id,
                version,
                lifecycle,
            )
        if row is None:
            raise GraphTemplateNotFound(
                f"no GraphTemplate {template_id!r} version {version} to promote"
            )

    async def lifecycle_of(self, template_id: str, version: int) -> TemplateLifecycle:
        """Absent reads as `active`.

        Rows written before ADR-082926-65bf carry no `lifecycle` key, and every
        one of them is an active reusable definition. Reading absence as
        `candidate` would hide the entire existing registry from unversioned
        resolution on the first deploy.
        """
        async with self._pool.acquire() as conn:
            found = await conn.fetchval(
                """SELECT COALESCE(payload->>'lifecycle', 'active') FROM graph_templates
                   WHERE template_id = $1 AND version = $2""",
                template_id,
                version,
            )
        if found is None:
            raise GraphTemplateNotFound(
                f"no GraphTemplate {template_id!r} version {version} is registered"
            )
        if found == "candidate":
            return "candidate"
        if found == "promoting":
            return "promoting"
        return "active"

    async def get(self, template_id: str, *, version: int | None = None) -> GraphTemplate | None:
        """Unversioned resolution returns the latest *active* version.

        `COALESCE(..., 'active') = 'active'` rather than a bare comparison: a
                row written before the lifecycle existed has no key, so `->>` yields
                NULL, and every such row *is* an active definition -- `= 'active'`
                alone would silently empty the registry. Coalescing first keeps those
                rows and excludes both `candidate` and the transitional `promoting`,
                which a `!= 'candidate'` test would have let through.
        """
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
                         AND COALESCE(payload->>'lifecycle', 'active') = 'active'
                       ORDER BY version DESC
                       LIMIT 1""",
                    template_id,
                )
        return model_of(GraphTemplate, payload) if payload is not None else None

    async def list_for_workspace(self, workspace_id: str) -> list[GraphTemplate]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload FROM graph_templates
                   WHERE workspace_id = $1
                   ORDER BY name, template_id, version""",
                workspace_id,
            )
        return [model_of(GraphTemplate, row["payload"]) for row in rows]

    async def versions(self, template_id: str) -> list[int]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT version FROM graph_templates WHERE template_id = $1 ORDER BY version",
                template_id,
            )
        return [int(row["version"]) for row in rows]


class PgNodeTemplateStore:
    """Durable NodeTemplate registry (#556).

    The same statement shape as `PgGraphTemplateStore`, against its own table,
    because the two families have the same identity and the same redefinition
    rule and differing here would be differing for no reason.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def put(self, template: NodeTemplate) -> NodeTemplate:
        """Register one version, idempotently for identical content.

        `DO UPDATE ... WHERE` rather than `DO NOTHING`, for the reason its
        GraphTemplate sibling records: on conflict this has to tell "already
        registered, same content" from "already registered, different content",
        and `DO NOTHING` returns no row either way.

        **Every promoted column moves with the payload, not just the payload.**
        `workspace_id`, `name` and `node_type` are copies of payload fields,
        lifted out so a listing is an index scan rather than a scan of JSON --
        and the content hash excludes `workspace_id` and includes the others
        only as content. So re-registering identical content under a different
        Workspace matched the predicate and updated the payload alone, leaving
        the column behind: `get` then returned a template naming the new
        Workspace while `list_for_workspace` still filed it under the old one,
        and neither the SQLite nor the in-memory store agreed with either
        (Codex, #563). A promoted column that can disagree with the payload it
        was promoted from is worse than no column.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO node_templates
                       (template_id, version, workspace_id, name, node_type, content_hash, payload)
                   VALUES ($1, $2, $3, $4, $5, $6, $7::text::jsonb)
                   ON CONFLICT (template_id, version) DO UPDATE
                       SET workspace_id = EXCLUDED.workspace_id,
                           name         = EXCLUDED.name,
                           node_type    = EXCLUDED.node_type,
                           payload      = jsonb_set(
                                          EXCLUDED.payload,
                                          '{lifecycle}',
                                          COALESCE(node_templates.payload->'lifecycle', '"active"'::jsonb),
                                          true
                                      )
                       WHERE node_templates.content_hash = EXCLUDED.content_hash
                   RETURNING template_id""",
                template.template_id,
                template.version,
                template.workspace_id,
                template.name,
                template.node_type,
                template.content_hash,
                json_of(revalidated(template)),
            )
        if row is None:
            raise NodeTemplateConflict(
                f"NodeTemplate {template.template_id!r} version {template.version} already "
                "exists with different content; register a new version instead"
            )
        return template

    async def set_lifecycle(
        self, template_id: str, version: int, lifecycle: TemplateLifecycle
    ) -> None:
        """The raw transition. `promote_audited` is the sanctioned path.

        `jsonb_set` rather than a rewritten payload: the lifecycle is the only
        thing moving, and rewriting the whole document to change one key would
        let an in-flight model change ride along with a promotion.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE node_templates
                       SET payload = jsonb_set(payload, '{lifecycle}', to_jsonb($3::text), true)
                   WHERE template_id = $1 AND version = $2
                   RETURNING template_id""",
                template_id,
                version,
                lifecycle,
            )
        if row is None:
            raise NodeTemplateNotFound(
                f"no NodeTemplate {template_id!r} version {version} to promote"
            )

    async def lifecycle_of(self, template_id: str, version: int) -> TemplateLifecycle:
        """Absent reads as `active`.

        Rows written before ADR-082926-65bf carry no `lifecycle` key, and every
        one of them is an active reusable definition. Reading absence as
        `candidate` would hide the entire existing registry from unversioned
        resolution on the first deploy.
        """
        async with self._pool.acquire() as conn:
            found = await conn.fetchval(
                """SELECT COALESCE(payload->>'lifecycle', 'active') FROM node_templates
                   WHERE template_id = $1 AND version = $2""",
                template_id,
                version,
            )
        if found is None:
            raise NodeTemplateNotFound(
                f"no NodeTemplate {template_id!r} version {version} is registered"
            )
        if found == "candidate":
            return "candidate"
        if found == "promoting":
            return "promoting"
        return "active"

    async def get(self, template_id: str, *, version: int | None = None) -> NodeTemplate | None:
        """Unversioned resolution returns the latest *active* version.

        Same rule and same NULL-tolerant predicate as its GraphTemplate sibling.
        """
        async with self._pool.acquire() as conn:
            if version is not None:
                payload: Any = await conn.fetchval(
                    "SELECT payload FROM node_templates WHERE template_id = $1 AND version = $2",
                    template_id,
                    version,
                )
            else:
                payload = await conn.fetchval(
                    """SELECT payload FROM node_templates
                       WHERE template_id = $1
                         AND COALESCE(payload->>'lifecycle', 'active') = 'active'
                       ORDER BY version DESC
                       LIMIT 1""",
                    template_id,
                )
        return model_of(NodeTemplate, payload) if payload is not None else None

    async def list_for_workspace(self, workspace_id: str) -> list[NodeTemplate]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload FROM node_templates
                   WHERE workspace_id = $1
                   ORDER BY name, template_id, version""",
                workspace_id,
            )
        return [model_of(NodeTemplate, row["payload"]) for row in rows]

    async def versions(self, template_id: str) -> list[int]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT version FROM node_templates WHERE template_id = $1 ORDER BY version",
                template_id,
            )
        return [int(row["version"]) for row in rows]


__all__ = ["PgGraphTemplateStore", "PgNodeTemplateStore"]
