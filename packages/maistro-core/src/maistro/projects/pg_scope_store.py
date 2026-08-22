"""PostgreSQL persistence for the canonical Workspace Project scope tree (#132).

The durable twin of `sqlite_scope_store.py`, against the system of record
ADR-082226-5104 names. Same protocol, same integrity rules, same errors — the
conformance suite runs one set of bodies against both, because "implements the
same protocol as" being a docstring rather than a test is how `PgStrikeTracker`
came to be unusable (#134).

What differs is not the SQL but the concurrency. SQLite serialises writers at
the database, so `create_root`'s read-then-insert cannot race. PostgreSQL does
not, so the partial unique index on `is_root` is the primary defence here rather
than a backstop: two callers can both see no root, and only one can insert one.

Payloads are JSONB and come back as dicts, because the pool registers a JSON
codec (`maistro.persistence._register_json_codecs`). That is why this reads
`model_validate` where the SQLite store reads `model_validate_json`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.projects.scope import (
    Project,
    ProjectIntegrityError,
    ProjectMembership,
    ProjectNotEmpty,
    ProjectNotFound,
    ProjectScopeDenied,
    ProjectScopedResource,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg


class PgProjectScopeStore:
    """Durable Project tree, membership, defaults, and scoped-resource store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_root(self, workspace_id: str) -> Project:
        """Create or return the Workspace's durable Root Project.

        `ON CONFLICT DO NOTHING` against the partial unique index, then read
        back. Checking first and inserting second would let two concurrent
        callers both find no root and both try to create one — the loser gets a
        unique violation rather than the root that now exists.
        """
        if not workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        root = Project(
            workspace_id=workspace_id,
            name="Root",
            parent_project_id=None,
            is_root=True,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO canonical_projects
                   (project_id, workspace_id, parent_project_id, is_root, payload)
                   VALUES ($1, $2, NULL, TRUE, $3)
                   ON CONFLICT DO NOTHING""",
                root.project_id,
                root.workspace_id,
                root.model_dump(mode="json"),
            )
        return await self.root_for_workspace(workspace_id)

    async def root_for_workspace(self, workspace_id: str) -> Project:
        root = await self._root_or_none(workspace_id)
        if root is None:
            raise ProjectNotFound(f"Root Project for Workspace {workspace_id!r}")
        return root

    async def create(
        self,
        *,
        workspace_id: str,
        parent_project_id: str,
        name: str,
        defaults: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Project:
        parent = await self._require(parent_project_id)
        if parent.workspace_id != workspace_id:
            raise ProjectIntegrityError("Project parent must belong to the same Workspace")
        project = Project(
            workspace_id=workspace_id,
            name=name,
            parent_project_id=parent_project_id,
            defaults=dict(defaults or {}),
            metadata=dict(metadata or {}),
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO canonical_projects
                   (project_id, workspace_id, parent_project_id, is_root, payload)
                   VALUES ($1, $2, $3, FALSE, $4)""",
                project.project_id,
                project.workspace_id,
                project.parent_project_id,
                project.model_dump(mode="json"),
            )
        return project

    async def get(self, project_id: str) -> Project | None:
        payload = await self._payload(
            "SELECT payload FROM canonical_projects WHERE project_id = $1", project_id
        )
        return Project.model_validate(payload) if payload is not None else None

    async def lineage(self, project_id: str) -> list[Project]:
        current = await self._require(project_id)
        workspace_id = current.workspace_id
        lineage: list[Project] = []
        seen: set[str] = set()

        while True:
            if current.project_id in seen:
                raise ProjectIntegrityError("Project tree contains a cycle")
            if current.workspace_id != workspace_id:
                raise ProjectIntegrityError("Project ancestry crossed a Workspace boundary")
            seen.add(current.project_id)
            lineage.append(current)
            if current.is_root:
                break
            if current.parent_project_id is None:
                raise ProjectIntegrityError("non-root Project lost its parent")
            current = await self._require(current.parent_project_id)

        lineage.reverse()
        return lineage

    async def list_children(self, project_id: str) -> list[Project]:
        await self._require(project_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT payload FROM canonical_projects WHERE parent_project_id = $1",
                project_id,
            )
        children = [Project.model_validate(row["payload"]) for row in rows]
        # Sorted in Python, not SQL: the ordering keys live inside the payload,
        # and an ORDER BY over JSONB extraction would be a different comparison
        # than the SQLite store's — the point of the conformance suite is that
        # they agree.
        children.sort(key=lambda item: (item.created_at, item.project_id))
        return children

    async def move_project(self, project_id: str, *, parent_project_id: str) -> Project:
        project = await self._require(project_id)
        if project.is_root:
            raise ProjectIntegrityError("Root Project cannot be moved")
        parent = await self._require(parent_project_id)
        if parent.workspace_id != project.workspace_id:
            raise ProjectIntegrityError("Project cannot move across Workspaces")
        if parent.project_id == project.project_id:
            raise ProjectIntegrityError("Project cannot be its own parent")
        ancestor_ids = {item.project_id for item in await self.lineage(parent_project_id)}
        if project.project_id in ancestor_ids:
            raise ProjectIntegrityError("Project move would create a cycle")

        updated = project.model_copy(
            update={
                "parent_project_id": parent_project_id,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._update_project(updated)
        return updated

    async def update_defaults(
        self,
        project_id: str,
        *,
        defaults: dict[str, Any],
    ) -> Project:
        project = await self._require(project_id)
        updated = project.model_copy(
            deep=True,
            update={"defaults": dict(defaults), "updated_at": datetime.now(UTC)},
        )
        await self._update_project(updated)
        return updated

    async def delete(self, project_id: str) -> None:
        project = await self._require(project_id)
        if project.is_root:
            raise ProjectIntegrityError("Root Project cannot be deleted")
        checks = (
            (
                "SELECT 1 FROM canonical_projects WHERE parent_project_id = $1 LIMIT 1",
                "Project has child Projects",
            ),
            (
                "SELECT 1 FROM canonical_project_resources WHERE project_id = $1 LIMIT 1",
                "Project has scoped resources",
            ),
            (
                "SELECT 1 FROM canonical_project_memberships WHERE project_id = $1 LIMIT 1",
                "Project has ProjectMembership records",
            ),
        )
        async with self._pool.acquire() as conn, conn.transaction():
            for sql, message in checks:
                if await conn.fetchval(sql, project_id) is not None:
                    raise ProjectNotEmpty(message)
            await conn.execute("DELETE FROM canonical_projects WHERE project_id = $1", project_id)

    async def resolve_creation_defaults(
        self,
        project_id: str,
        *,
        workspace_defaults: dict[str, Any] | None = None,
        persona_defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved = dict(workspace_defaults or {})
        resolved.update(persona_defaults or {})
        for project in await self.lineage(project_id):
            resolved.update(project.defaults)
        return resolved

    async def set_membership(self, membership: ProjectMembership) -> ProjectMembership:
        project = await self._require(membership.project_id)
        if project.workspace_id != membership.workspace_id:
            raise ProjectIntegrityError("ProjectMembership Workspace does not match Project")
        existing = await self._membership_or_none(membership.membership_id)
        if existing is not None and existing.workspace_id != membership.workspace_id:
            raise ProjectIntegrityError("membership identity cannot cross Workspaces")
        updated = membership.model_copy(update={"updated_at": datetime.now(UTC)})
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO canonical_project_memberships
                   (membership_id, workspace_id, project_id, principal_id, payload)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (membership_id) DO UPDATE SET
                     workspace_id = EXCLUDED.workspace_id,
                     project_id = EXCLUDED.project_id,
                     principal_id = EXCLUDED.principal_id,
                     payload = EXCLUDED.payload""",
                updated.membership_id,
                updated.workspace_id,
                updated.project_id,
                updated.principal_id,
                updated.model_dump(mode="json"),
            )
        return updated

    async def memberships_for(
        self,
        project_id: str,
        *,
        principal_id: str | None = None,
    ) -> list[ProjectMembership]:
        await self._require(project_id)
        sql = "SELECT payload FROM canonical_project_memberships WHERE project_id = $1"
        params: tuple[str, ...] = (project_id,)
        if principal_id is not None:
            sql += " AND principal_id = $2"
            params = (project_id, principal_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        memberships = [ProjectMembership.model_validate(row["payload"]) for row in rows]
        memberships.sort(key=lambda item: (item.created_at, item.membership_id))
        return memberships

    async def put_resource(self, resource: ProjectScopedResource) -> ProjectScopedResource:
        project = await self._require(resource.project_id)
        if project.workspace_id != resource.workspace_id:
            raise ProjectIntegrityError("resource Workspace does not match Project")
        existing = await self._resource_or_none(resource.resource_id)
        if existing is not None and existing.workspace_id != resource.workspace_id:
            raise ProjectIntegrityError("resource identity cannot cross Workspaces")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO canonical_project_resources
                   (resource_id, workspace_id, project_id, resource_type, payload)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (resource_id) DO UPDATE SET
                     workspace_id = EXCLUDED.workspace_id,
                     project_id = EXCLUDED.project_id,
                     resource_type = EXCLUDED.resource_type,
                     payload = EXCLUDED.payload""",
                resource.resource_id,
                resource.workspace_id,
                resource.project_id,
                resource.resource_type,
                resource.model_dump(mode="json"),
            )
        return resource

    async def visible_resources(
        self,
        project_id: str,
        *,
        resource_type: str | None = None,
    ) -> list[ProjectScopedResource]:
        lineage = await self.lineage(project_id)
        project_ids = {project.project_id for project in lineage}
        workspace_id = lineage[-1].workspace_id
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT payload FROM canonical_project_resources WHERE workspace_id = $1",
                workspace_id,
            )
        resources = [ProjectScopedResource.model_validate(row["payload"]) for row in rows]
        visible = [
            resource
            for resource in resources
            if resource.project_id in project_ids
            and (resource_type is None or resource.resource_type == resource_type)
        ]
        visible.sort(key=lambda item: (item.resource_type, item.resource_id))
        return visible

    async def validate_required_resources(
        self,
        project_id: str,
        resource_ids: set[str],
    ) -> None:
        visible = {resource.resource_id for resource in await self.visible_resources(project_id)}
        missing = sorted(resource_ids - visible)
        if missing:
            raise ProjectScopeDenied(
                f"destination Project cannot see required resources: {', '.join(missing)}"
            )

    # ── internals ─────────────────────────────────────────────────

    async def _update_project(self, project: Project) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE canonical_projects
                   SET parent_project_id = $1, payload = $2
                   WHERE project_id = $3""",
                project.parent_project_id,
                project.model_dump(mode="json"),
                project.project_id,
            )

    async def _root_or_none(self, workspace_id: str) -> Project | None:
        payload = await self._payload(
            "SELECT payload FROM canonical_projects WHERE workspace_id = $1 AND is_root",
            workspace_id,
        )
        return Project.model_validate(payload) if payload is not None else None

    async def _membership_or_none(self, membership_id: str) -> ProjectMembership | None:
        payload = await self._payload(
            "SELECT payload FROM canonical_project_memberships WHERE membership_id = $1",
            membership_id,
        )
        return ProjectMembership.model_validate(payload) if payload is not None else None

    async def _resource_or_none(self, resource_id: str) -> ProjectScopedResource | None:
        payload = await self._payload(
            "SELECT payload FROM canonical_project_resources WHERE resource_id = $1",
            resource_id,
        )
        return ProjectScopedResource.model_validate(payload) if payload is not None else None

    async def _require(self, project_id: str) -> Project:
        project = await self.get(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project

    async def _payload(self, sql: str, *params: Any) -> Any | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(sql, *params)


__all__ = ["PgProjectScopeStore"]
