"""Reference persistence for the canonical Workspace Project scope tree."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from maistro.projects.scope import (
    Project,
    ProjectIntegrityError,
    ProjectMembership,
    ProjectNotEmpty,
    ProjectNotFound,
    ProjectScopeDenied,
    ProjectScopedResource,
)


@runtime_checkable
class ProjectScopeStore(Protocol):
    """Persistence boundary for the canonical Workspace Project tree."""

    async def create_root(self, workspace_id: str) -> Project:
        """Create or return the Workspace's single Root Project."""

        ...

    async def root_for_workspace(self, workspace_id: str) -> Project:
        """Return the canonical Root Project for a Workspace."""

        ...

    async def create(
        self,
        *,
        workspace_id: str,
        parent_project_id: str,
        name: str,
        defaults: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Project:
        """Create a child Project beneath a same-Workspace parent."""

        ...

    async def get(self, project_id: str) -> Project | None:
        """Return a Project by ID, or ``None`` when it does not exist."""

        ...

    async def lineage(self, project_id: str) -> list[Project]:
        """Return the Project lineage ordered from Root Project to target."""

        ...

    async def list_children(self, project_id: str) -> list[Project]:
        """Return the target Project's direct children."""

        ...

    async def move_project(self, project_id: str, *, parent_project_id: str) -> Project:
        """Move a non-root Project beneath a valid same-Workspace parent."""

        ...

    async def update_defaults(self, project_id: str, *, defaults: dict[str, Any]) -> Project:
        """Replace the defaults owned by a Project."""

        ...

    async def delete(self, project_id: str) -> None:
        """Delete an empty non-root Project."""

        ...

    async def resolve_creation_defaults(
        self,
        project_id: str,
        *,
        workspace_defaults: dict[str, Any] | None = None,
        persona_defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve creation defaults from Workspace, Persona, and ancestry."""

        ...

    async def set_membership(self, membership: ProjectMembership) -> ProjectMembership:
        """Create or replace a Project-scoped membership."""

        ...

    async def memberships_for(
        self, project_id: str, *, principal_id: str | None = None
    ) -> list[ProjectMembership]:
        """List memberships at one Project, optionally for one principal."""

        ...

    async def put_resource(self, resource: ProjectScopedResource) -> ProjectScopedResource:
        """Create or replace a resource owned by a Project."""

        ...

    async def visible_resources(
        self, project_id: str, *, resource_type: str | None = None
    ) -> list[ProjectScopedResource]:
        """List resources visible from the target Project's ancestry."""

        ...

    async def validate_required_resources(
        self,
        project_id: str,
        resource_ids: set[str],
    ) -> None:
        """Reject required resources that are not visible at the target."""

        ...


class InMemoryProjectScopeStore:
    """Reference Project tree with downward-only scoped-resource visibility."""

    def __init__(self) -> None:
        """Initialize an empty isolated Project tree store."""

        self._projects: dict[str, Project] = {}
        self._root_by_workspace: dict[str, str] = {}
        self._memberships: dict[str, ProjectMembership] = {}
        self._resources: dict[str, ProjectScopedResource] = {}

    async def create_root(self, workspace_id: str) -> Project:
        """Create or return the Workspace's single Root Project."""

        if not workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        existing_id = self._root_by_workspace.get(workspace_id)
        if existing_id is not None:
            return self._projects[existing_id].model_copy(deep=True)

        root = Project(
            workspace_id=workspace_id,
            name="Root",
            parent_project_id=None,
            is_root=True,
        )
        self._projects[root.project_id] = root
        self._root_by_workspace[workspace_id] = root.project_id
        return root.model_copy(deep=True)

    async def root_for_workspace(self, workspace_id: str) -> Project:
        """Return the canonical Root Project for a Workspace."""

        root_id = self._root_by_workspace.get(workspace_id)
        if root_id is None:
            raise ProjectNotFound(f"Root Project for Workspace {workspace_id!r}")
        return self._projects[root_id].model_copy(deep=True)

    async def create(
        self,
        *,
        workspace_id: str,
        parent_project_id: str,
        name: str,
        defaults: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Project:
        """Create a child Project beneath a same-Workspace parent."""

        parent = self._require(parent_project_id)
        if parent.workspace_id != workspace_id:
            raise ProjectIntegrityError("Project parent must belong to the same Workspace")
        project = Project(
            workspace_id=workspace_id,
            name=name,
            parent_project_id=parent_project_id,
            defaults=dict(defaults or {}),
            metadata=dict(metadata or {}),
        )
        self._projects[project.project_id] = project
        return project.model_copy(deep=True)

    async def get(self, project_id: str) -> Project | None:
        """Return a detached Project snapshot by ID when present."""

        project = self._projects.get(project_id)
        return project.model_copy(deep=True) if project is not None else None

    async def lineage(self, project_id: str) -> list[Project]:
        """Return validated ancestry ordered from Root Project to target."""

        lineage: list[Project] = []
        seen: set[str] = set()
        current = self._require(project_id)
        workspace_id = current.workspace_id

        while True:
            if current.project_id in seen:
                raise ProjectIntegrityError("Project tree contains a cycle")
            seen.add(current.project_id)
            if current.workspace_id != workspace_id:
                raise ProjectIntegrityError("Project ancestry crossed a Workspace boundary")
            lineage.append(current)
            if current.is_root:
                break
            if current.parent_project_id is None:
                raise ProjectIntegrityError("non-root Project lost its parent")
            current = self._require(current.parent_project_id)

        lineage.reverse()
        return [project.model_copy(deep=True) for project in lineage]

    async def list_children(self, project_id: str) -> list[Project]:
        """Return detached snapshots of the target's direct children."""

        self._require(project_id)
        children = [
            project.model_copy(deep=True)
            for project in self._projects.values()
            if project.parent_project_id == project_id
        ]
        children.sort(key=lambda item: (item.created_at, item.project_id))
        return children

    async def move_project(self, project_id: str, *, parent_project_id: str) -> Project:
        """Move a non-root Project without crossing Workspaces or forming a cycle."""

        project = self._require(project_id)
        if project.is_root:
            raise ProjectIntegrityError("Root Project cannot be moved")
        parent = self._require(parent_project_id)
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
        self._projects[project_id] = updated
        return updated.model_copy(deep=True)

    async def update_defaults(
        self,
        project_id: str,
        *,
        defaults: dict[str, Any],
    ) -> Project:
        """Replace a Project's defaults and advance its update timestamp."""

        project = self._require(project_id)
        updated = project.model_copy(
            deep=True,
            update={"defaults": dict(defaults), "updated_at": datetime.now(UTC)},
        )
        self._projects[project_id] = updated
        return updated.model_copy(deep=True)

    async def delete(self, project_id: str) -> None:
        """Delete an empty non-root Project while preserving owned records."""

        project = self._require(project_id)
        if project.is_root:
            raise ProjectIntegrityError("Root Project cannot be deleted")
        if any(item.parent_project_id == project_id for item in self._projects.values()):
            raise ProjectNotEmpty("Project has child Projects")
        if any(item.project_id == project_id for item in self._resources.values()):
            raise ProjectNotEmpty("Project has scoped resources")
        if any(item.project_id == project_id for item in self._memberships.values()):
            raise ProjectNotEmpty("Project has ProjectMembership records")
        del self._projects[project_id]

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
        """Create or replace a membership after validating Project ownership."""

        project = self._require(membership.project_id)
        if project.workspace_id != membership.workspace_id:
            raise ProjectIntegrityError("ProjectMembership Workspace does not match Project")
        updated = membership.model_copy(update={"updated_at": datetime.now(UTC)})
        self._memberships[membership.membership_id] = updated
        return updated.model_copy(deep=True)

    async def memberships_for(
        self,
        project_id: str,
        *,
        principal_id: str | None = None,
    ) -> list[ProjectMembership]:
        """List detached memberships at a Project, optionally for one principal."""

        self._require(project_id)
        memberships = [
            membership.model_copy(deep=True)
            for membership in self._memberships.values()
            if membership.project_id == project_id
            and (principal_id is None or membership.principal_id == principal_id)
        ]
        memberships.sort(key=lambda item: (item.created_at, item.membership_id))
        return memberships

    async def put_resource(self, resource: ProjectScopedResource) -> ProjectScopedResource:
        """Create or replace a Project resource without crossing Workspaces."""

        project = self._require(resource.project_id)
        if project.workspace_id != resource.workspace_id:
            raise ProjectIntegrityError("resource Workspace does not match Project")
        existing = self._resources.get(resource.resource_id)
        if existing is not None and existing.workspace_id != resource.workspace_id:
            raise ProjectIntegrityError("resource identity cannot cross Workspaces")
        self._resources[resource.resource_id] = resource.model_copy(deep=True)
        return resource.model_copy(deep=True)

    async def visible_resources(
        self,
        project_id: str,
        *,
        resource_type: str | None = None,
    ) -> list[ProjectScopedResource]:
        """Return resources owned by the target Project or its ancestors."""

        ancestry = {project.project_id for project in await self.lineage(project_id)}
        resources = [
            resource.model_copy(deep=True)
            for resource in self._resources.values()
            if resource.project_id in ancestry
            and (resource_type is None or resource.resource_type == resource_type)
        ]
        resources.sort(key=lambda item: (item.resource_type, item.resource_id))
        return resources

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

    def purge_workspace(self, workspace_id: str) -> None:
        """Internal Workspace teardown helper; not ordinary Project deletion."""

        project_ids = {
            project.project_id
            for project in self._projects.values()
            if project.workspace_id == workspace_id
        }
        for membership_id in [
            membership_id
            for membership_id, membership in self._memberships.items()
            if membership.workspace_id == workspace_id
        ]:
            del self._memberships[membership_id]
        for resource_id in [
            resource_id
            for resource_id, resource in self._resources.items()
            if resource.workspace_id == workspace_id
        ]:
            del self._resources[resource_id]
        for project_id in project_ids:
            del self._projects[project_id]
        self._root_by_workspace.pop(workspace_id, None)

    def _require(self, project_id: str) -> Project:
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project


__all__ = ["InMemoryProjectScopeStore", "ProjectScopeStore"]
