"""Project-tree authorization and resource visibility contracts.

This module is deliberately independent from Persona and from the legacy
``Project.members`` role model. It provides the small, pure authorization
contract used by callers that already hold canonical Project ancestry.

Production Project authorization should obtain ancestry and persisted
ProjectMembership records from ``maistro.projects.ProjectScopeStore`` and use
``maistro.projects.resolve_project_authorization``. This module must mirror the
same architectural invariants:

* an active Workspace membership is required;
* authority may increase as scope narrows;
* Project grants apply only inside their Project subtree;
* inherited denies are sticky and always win;
* Project-scoped resources flow downward to descendants, never upward or sideways;
* Workspace-scoped resources are visible anywhere in the Workspace;
* Persona never participates in authorization.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

Permission = str


class MembershipStatus(StrEnum):
    """Whether a membership currently participates in authorization."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class WorkspaceMembership:
    """A principal's authorization membership in a Workspace."""

    workspace_id: str
    principal_id: str
    grants: frozenset[Permission] = field(default_factory=frozenset)
    denies: frozenset[Permission] = field(default_factory=frozenset)
    status: MembershipStatus = MembershipStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class ProjectMembership:
    """A principal's authorization additions/restrictions at one Project scope.

    Project grants are additive within the Project subtree. They do not need to
    be present at Workspace scope first. A grant issued at one Project never
    applies to its parent, sibling, or another unrelated subtree.
    """

    workspace_id: str
    project_id: str
    principal_id: str
    grants: frozenset[Permission] = field(default_factory=frozenset)
    denies: frozenset[Permission] = field(default_factory=frozenset)
    status: MembershipStatus = MembershipStatus.ACTIVE


class ResourceKind(StrEnum):
    """Resource families whose visibility/use can be scoped by authorization."""

    CREDENTIAL = "credential"
    BINDING = "binding"
    POLICY = "policy"
    GENERIC = "generic"


class ResourceScopeKind(StrEnum):
    WORKSPACE = "workspace"
    PROJECT = "project"


@dataclass(frozen=True, slots=True)
class ResourceScope:
    """Ownership/visibility scope for a Credential, Binding, policy, or peer resource."""

    workspace_id: str
    kind: ResourceScopeKind
    project_id: str | None = None
    resource_kind: ResourceKind = ResourceKind.GENERIC

    def __post_init__(self) -> None:
        if self.kind is ResourceScopeKind.PROJECT and not self.project_id:
            raise ValueError("project-scoped resources require project_id")
        if self.kind is ResourceScopeKind.WORKSPACE and self.project_id is not None:
            raise ValueError("workspace-scoped resources cannot carry project_id")


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Explainable result of resolving one permission request."""

    allowed: bool
    permission: Permission
    effective_permissions: frozenset[Permission]
    denied_permissions: frozenset[Permission]
    reason: str


class AuthorizationResolver:
    """Evaluate permissions over canonical Project ancestry supplied by the caller.

    ``project_path`` is ordered Root Project -> target. Production callers should
    obtain that path from ``ProjectScopeStore.lineage`` rather than constructing a
    hierarchy ad hoc. The resolver intentionally has no Persona input or dependency.
    """

    def resolve(
        self,
        *,
        permission: Permission,
        workspace_membership: WorkspaceMembership | None,
        project_path: Iterable[str] = (),
        project_memberships: Iterable[ProjectMembership] = (),
    ) -> AuthorizationDecision:
        if (
            workspace_membership is None
            or workspace_membership.status is not MembershipStatus.ACTIVE
        ):
            return AuthorizationDecision(
                allowed=False,
                permission=permission,
                effective_permissions=frozenset(),
                denied_permissions=frozenset(),
                reason="active workspace membership required",
            )

        path = tuple(project_path)
        overlays = self._overlays_for_path(
            workspace_membership=workspace_membership,
            project_path=path,
            project_memberships=project_memberships,
        )

        effective = set(workspace_membership.grants)
        denied = set(workspace_membership.denies)
        effective.difference_update(denied)

        for membership in overlays:
            if membership.status is not MembershipStatus.ACTIVE:
                return AuthorizationDecision(
                    allowed=False,
                    permission=permission,
                    effective_permissions=frozenset(),
                    denied_permissions=frozenset(denied),
                    reason=f"project membership suspended at {membership.project_id}",
                )
            effective.update(membership.grants)
            denied.update(membership.denies)
            effective.difference_update(denied)

        allowed = permission in effective and permission not in denied
        return AuthorizationDecision(
            allowed=allowed,
            permission=permission,
            effective_permissions=frozenset(effective),
            denied_permissions=frozenset(denied),
            reason="allowed" if allowed else "permission not granted or explicitly denied",
        )

    def can_view_resource(
        self,
        *,
        scope: ResourceScope,
        workspace_membership: WorkspaceMembership | None,
        project_path: Iterable[str] = (),
    ) -> bool:
        """Return whether a principal can see a scoped resource.

        This is ownership visibility only. Call ``resolve`` separately for the
        action permission required to read/use/mutate that resource.

        ``project_path`` is Root Project -> target. A Project-scoped resource is
        visible when its owning Project is on the target's ancestry, so resources
        flow downward to descendants but never upward to parents or sideways to
        siblings.
        """
        if (
            workspace_membership is None
            or workspace_membership.status is not MembershipStatus.ACTIVE
            or workspace_membership.workspace_id != scope.workspace_id
        ):
            return False
        if scope.kind is ResourceScopeKind.WORKSPACE:
            return True
        return scope.project_id in tuple(project_path)

    @staticmethod
    def _overlays_for_path(
        *,
        workspace_membership: WorkspaceMembership,
        project_path: tuple[str, ...],
        project_memberships: Iterable[ProjectMembership],
    ) -> tuple[ProjectMembership, ...]:
        by_project: dict[str, ProjectMembership] = {}
        for membership in project_memberships:
            if membership.workspace_id != workspace_membership.workspace_id:
                continue
            if membership.principal_id != workspace_membership.principal_id:
                continue
            if membership.project_id in by_project:
                raise ValueError(f"duplicate project membership for {membership.project_id}")
            by_project[membership.project_id] = membership

        return tuple(
            by_project[project_id] for project_id in project_path if project_id in by_project
        )
