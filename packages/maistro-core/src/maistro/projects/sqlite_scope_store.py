"""SQLite persistence for the canonical Workspace Project scope tree."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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

if TYPE_CHECKING:
    import aiosqlite

#: Passes the leaf-first Project purge may take before it gives up. A Workspace
#: tree deeper than this is pathological, and a loop that cannot terminate is
#: worse than one that refuses.
_MAX_PURGE_PASSES = 64

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS canonical_projects (
    project_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    parent_project_id TEXT,
    is_root INTEGER NOT NULL CHECK (is_root IN (0, 1)),
    payload TEXT NOT NULL,
    FOREIGN KEY (parent_project_id) REFERENCES canonical_projects(project_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_projects_one_root
    ON canonical_projects(workspace_id)
    WHERE is_root = 1;
CREATE INDEX IF NOT EXISTS idx_canonical_projects_parent
    ON canonical_projects(parent_project_id);
CREATE INDEX IF NOT EXISTS idx_canonical_projects_workspace
    ON canonical_projects(workspace_id);

CREATE TABLE IF NOT EXISTS canonical_project_memberships (
    membership_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES canonical_projects(project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_canonical_project_memberships_project_principal
    ON canonical_project_memberships(project_id, principal_id);

CREATE TABLE IF NOT EXISTS canonical_project_resources (
    resource_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES canonical_projects(project_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_canonical_project_resources_project_type
    ON canonical_project_resources(project_id, resource_type);
"""


class SqliteProjectScopeStore:
    """Durable Project tree, membership, defaults, and scoped-resource store."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        """Bind the store to an application-owned SQLite connection."""

        self._conn = conn
        self._owns_runs: Callable[[str], Awaitable[bool]] | None = None

    def set_run_owner(self, owns_runs: Callable[[str], Awaitable[bool]]) -> None:
        """Register the predicate `delete()` consults for Run ownership."""

        self._owns_runs = owns_runs

    async def ensure_schema(self) -> None:
        """Create canonical Project tables and integrity indexes."""

        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def purge_workspace(self, workspace_id: str) -> None:
        """Tear down every Project row this Workspace owns.

        Children before parents, because both schemas declare
        `ON DELETE RESTRICT` on the self-referencing parent link and on the
        membership and resource links -- so a single bulk delete fails on the
        first row whose child is still present. Rather than compute depth,
        this deletes the current leaves and repeats: the set shrinks by at
        least one level each pass, so it terminates in tree-depth passes.

        The bound is not decoration. A cycle cannot exist -- `move_project`
        refuses one -- but a spin here would hang a delete request rather than
        fail it, and a loop whose termination depends on an invariant enforced
        somewhere else should say so out loud when the invariant breaks.
        """
        await self._conn.execute(
            "DELETE FROM canonical_project_resources WHERE workspace_id = ?",
            (workspace_id,),
        )
        await self._conn.execute(
            "DELETE FROM canonical_project_memberships WHERE workspace_id = ?",
            (workspace_id,),
        )
        for _ in range(_MAX_PURGE_PASSES):
            cursor = await self._conn.execute(
                """DELETE FROM canonical_projects
                    WHERE workspace_id = ?
                      AND project_id NOT IN (
                          SELECT parent_project_id
                            FROM canonical_projects
                           WHERE workspace_id = ?
                             AND parent_project_id IS NOT NULL)""",
                (workspace_id, workspace_id),
            )
            if cursor.rowcount == 0:
                await self._conn.commit()
                return
        await self._conn.rollback()
        msg = (
            f"Project tree for workspace {workspace_id} did not drain in "
            f"{_MAX_PURGE_PASSES} passes; it is deeper than that or cyclic"
        )
        raise ProjectIntegrityError(msg)

    async def create_root(self, workspace_id: str) -> Project:
        """Create or return the Workspace's durable Root Project."""

        if not workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        existing = await self._root_or_none(workspace_id)
        if existing is not None:
            return existing

        root = Project(
            workspace_id=workspace_id,
            name="Root",
            parent_project_id=None,
            is_root=True,
        )
        await self._conn.execute(
            """INSERT OR IGNORE INTO canonical_projects
               (project_id, workspace_id, parent_project_id, is_root, payload)
               VALUES (?, ?, NULL, 1, ?)""",
            (root.project_id, root.workspace_id, root.model_dump_json()),
        )
        await self._conn.commit()
        return await self.root_for_workspace(workspace_id)

    async def root_for_workspace(self, workspace_id: str) -> Project:
        """Return the canonical Root Project for a Workspace."""

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
        """Persist a child Project beneath a same-Workspace parent."""

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
        await self._insert_project(project)
        return project

    async def get(self, project_id: str) -> Project | None:
        """Load a Project by ID, or return ``None`` when absent."""

        row = await self._fetchone(
            "SELECT payload FROM canonical_projects WHERE project_id = ?",
            (project_id,),
        )
        return Project.model_validate_json(row[0]) if row is not None else None

    async def lineage(self, project_id: str) -> list[Project]:
        """Load validated ancestry ordered from Root Project to target."""

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
        """Load the target Project's direct children in stable order."""

        await self._require(project_id)
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_projects WHERE parent_project_id = ?",
            (project_id,),
        )
        rows = await cursor.fetchall()
        children = [Project.model_validate_json(row[0]) for row in rows]
        children.sort(key=lambda item: (item.created_at, item.project_id))
        return children

    async def move_project(self, project_id: str, *, parent_project_id: str) -> Project:
        """Move a non-root Project without crossing Workspaces or forming a cycle."""

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
        """Replace a Project's defaults and persist its update timestamp."""

        project = await self._require(project_id)
        updated = project.model_copy(
            deep=True,
            update={"defaults": dict(defaults), "updated_at": datetime.now(UTC)},
        )
        await self._update_project(updated)
        return updated

    async def delete(self, project_id: str) -> None:
        """Delete an empty non-root Project while retaining integrity checks."""

        project = await self._require(project_id)
        if project.is_root:
            raise ProjectIntegrityError("Root Project cannot be deleted")
        if await self._exists(
            "SELECT 1 FROM canonical_projects WHERE parent_project_id = ? LIMIT 1",
            (project_id,),
        ):
            raise ProjectNotEmpty("Project has child Projects")
        if await self._exists(
            "SELECT 1 FROM canonical_project_resources WHERE project_id = ? LIMIT 1",
            (project_id,),
        ):
            raise ProjectNotEmpty("Project has scoped resources")
        if await self._exists(
            "SELECT 1 FROM canonical_project_memberships WHERE project_id = ? LIMIT 1",
            (project_id,),
        ):
            raise ProjectNotEmpty("Project has ProjectMembership records")
        # The Run tables belong to `runs.sqlite_store`, so this store asks
        # rather than joining: deleting a Project out from under its Run history
        # is the rule, and only the Run store can answer whether it applies.
        # PostgreSQL expresses the same rule as a foreign key.
        if self._owns_runs is not None and await self._owns_runs(project_id):
            raise ProjectNotEmpty("Project has canonical Runs")
        await self._conn.execute(
            "DELETE FROM canonical_projects WHERE project_id = ?",
            (project_id,),
        )
        await self._conn.commit()

    async def resolve_creation_defaults(
        self,
        project_id: str,
        *,
        workspace_defaults: dict[str, Any] | None = None,
        persona_defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge creation defaults in Workspace, Persona, then lineage order."""

        resolved = dict(workspace_defaults or {})
        resolved.update(persona_defaults or {})
        for project in await self.lineage(project_id):
            resolved.update(project.defaults)
        return resolved

    async def set_membership(self, membership: ProjectMembership) -> ProjectMembership:
        """Upsert a membership after validating its Workspace ownership."""

        project = await self._require(membership.project_id)
        if project.workspace_id != membership.workspace_id:
            raise ProjectIntegrityError("ProjectMembership Workspace does not match Project")
        existing = await self._membership_or_none(membership.membership_id)
        if existing is not None and existing.workspace_id != membership.workspace_id:
            raise ProjectIntegrityError("membership identity cannot cross Workspaces")
        updated = membership.model_copy(update={"updated_at": datetime.now(UTC)})
        await self._conn.execute(
            """INSERT INTO canonical_project_memberships
               (membership_id, workspace_id, project_id, principal_id, payload)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(membership_id) DO UPDATE SET
                 workspace_id = excluded.workspace_id,
                 project_id = excluded.project_id,
                 principal_id = excluded.principal_id,
                 payload = excluded.payload""",
            (
                updated.membership_id,
                updated.workspace_id,
                updated.project_id,
                updated.principal_id,
                updated.model_dump_json(),
            ),
        )
        await self._conn.commit()
        return updated

    async def memberships_for(
        self,
        project_id: str,
        *,
        principal_id: str | None = None,
    ) -> list[ProjectMembership]:
        """Load memberships at one Project, optionally for one principal."""

        await self._require(project_id)
        sql = "SELECT payload FROM canonical_project_memberships WHERE project_id = ?"
        params: tuple[str, ...] = (project_id,)
        if principal_id is not None:
            sql += " AND principal_id = ?"
            params = (project_id, principal_id)
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        memberships = [ProjectMembership.model_validate_json(row[0]) for row in rows]
        memberships.sort(key=lambda item: (item.created_at, item.membership_id))
        return memberships

    async def put_resource(self, resource: ProjectScopedResource) -> ProjectScopedResource:
        """Upsert a Project resource without allowing cross-Workspace reuse."""

        project = await self._require(resource.project_id)
        if project.workspace_id != resource.workspace_id:
            raise ProjectIntegrityError("resource Workspace does not match Project")
        existing = await self._resource_or_none(resource.resource_id)
        if existing is not None and existing.workspace_id != resource.workspace_id:
            raise ProjectIntegrityError("resource identity cannot cross Workspaces")
        await self._conn.execute(
            """INSERT INTO canonical_project_resources
               (resource_id, workspace_id, project_id, resource_type, payload)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(resource_id) DO UPDATE SET
                 workspace_id = excluded.workspace_id,
                 project_id = excluded.project_id,
                 resource_type = excluded.resource_type,
                 payload = excluded.payload""",
            (
                resource.resource_id,
                resource.workspace_id,
                resource.project_id,
                resource.resource_type,
                resource.model_dump_json(),
            ),
        )
        await self._conn.commit()
        return resource

    async def visible_resources(
        self,
        project_id: str,
        *,
        resource_type: str | None = None,
    ) -> list[ProjectScopedResource]:
        """Load resources owned by the target Project or its ancestors."""

        lineage = await self.lineage(project_id)
        project_ids = {project.project_id for project in lineage}
        workspace_id = lineage[-1].workspace_id
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_project_resources WHERE workspace_id = ?",
            (workspace_id,),
        )
        rows = await cursor.fetchall()
        resources = [ProjectScopedResource.model_validate_json(row[0]) for row in rows]
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
        """Reject resource IDs outside the target Project's visible ancestry."""

        visible = {resource.resource_id for resource in await self.visible_resources(project_id)}
        missing = sorted(resource_ids - visible)
        if missing:
            raise ProjectScopeDenied(
                f"destination Project cannot see required resources: {', '.join(missing)}"
            )

    async def _insert_project(self, project: Project) -> None:
        await self._conn.execute(
            """INSERT INTO canonical_projects
               (project_id, workspace_id, parent_project_id, is_root, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (
                project.project_id,
                project.workspace_id,
                project.parent_project_id,
                int(project.is_root),
                project.model_dump_json(),
            ),
        )
        await self._conn.commit()

    async def _update_project(self, project: Project) -> None:
        await self._conn.execute(
            """UPDATE canonical_projects
               SET parent_project_id = ?, payload = ?
               WHERE project_id = ?""",
            (project.parent_project_id, project.model_dump_json(), project.project_id),
        )
        await self._conn.commit()

    async def _root_or_none(self, workspace_id: str) -> Project | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_projects WHERE workspace_id = ? AND is_root = 1",
            (workspace_id,),
        )
        return Project.model_validate_json(row[0]) if row is not None else None

    async def _membership_or_none(self, membership_id: str) -> ProjectMembership | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_project_memberships WHERE membership_id = ?",
            (membership_id,),
        )
        return ProjectMembership.model_validate_json(row[0]) if row is not None else None

    async def _resource_or_none(self, resource_id: str) -> ProjectScopedResource | None:
        row = await self._fetchone(
            "SELECT payload FROM canonical_project_resources WHERE resource_id = ?",
            (resource_id,),
        )
        return ProjectScopedResource.model_validate_json(row[0]) if row is not None else None

    async def _require(self, project_id: str) -> Project:
        project = await self.get(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project

    async def _exists(self, sql: str, params: tuple[str, ...]) -> bool:
        return await self._fetchone(sql, params) is not None

    async def _fetchone(
        self,
        sql: str,
        params: tuple[str, ...],
    ) -> tuple[Any, ...] | None:
        cursor = await self._conn.execute(sql, params)
        row = await cursor.fetchone()
        return tuple(row) if row is not None else None


__all__ = ["SqliteProjectScopeStore"]
