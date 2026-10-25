"""Scope-bound authorization resolution for the canonical Project tree."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from maistro.projects.scope import Project, ProjectMembership, ProjectScopeDenied
from maistro.projects.scope_store import ProjectScopeStore

if TYPE_CHECKING:
    from maistro.workspaces.store import WorkspaceStore


@dataclass(frozen=True, slots=True)
class EffectiveAuthorization:
    """Resolved grants and denies at one target Project scope."""

    grants: frozenset[str]
    denies: frozenset[str]
    delegable_grants: frozenset[str]

    def allows(self, action: str) -> bool:
        """Return whether the resolved scope permits an action."""

        return action in self.grants and action not in self.denies

    def can_delegate(self, action: str) -> bool:
        """Return whether the action is both allowed and delegable."""

        return self.allows(action) and action in self.delegable_grants


async def resolve_project_authorization(
    store: ProjectScopeStore,
    *,
    project_id: str,
    principal_id: str,
    workspace_grants: Iterable[str] = (),
    workspace_denies: Iterable[str] = (),
    workspace_delegable_grants: Iterable[str] = (),
    object_grants: Iterable[str] = (),
    object_denies: Iterable[str] = (),
) -> EffectiveAuthorization:
    """Accumulate applicable scope-bound grants with deny-wins semantics."""

    grants = set(workspace_grants)
    denies = set(workspace_denies)
    delegable = set(workspace_delegable_grants)

    for project in await store.lineage(project_id):
        memberships = await store.memberships_for(
            project.project_id,
            principal_id=principal_id,
        )
        for membership in memberships:
            grants.update(membership.grants)
            denies.update(membership.denies)
            delegable.update(membership.delegable_grants)

    grants.update(object_grants)
    denies.update(object_denies)

    effective_grants = grants - denies
    effective_delegable = delegable.intersection(effective_grants)
    return EffectiveAuthorization(
        grants=frozenset(effective_grants),
        denies=frozenset(denies),
        delegable_grants=frozenset(effective_delegable),
    )


async def require_delegable_grant(
    store: ProjectScopeStore,
    *,
    project_id: str,
    principal_id: str,
    action: str,
    workspace_grants: Iterable[str] = (),
    workspace_denies: Iterable[str] = (),
    workspace_delegable_grants: Iterable[str] = (),
) -> None:
    """Reject an attempt to grant authority the principal cannot delegate."""

    effective = await resolve_project_authorization(
        store,
        project_id=project_id,
        principal_id=principal_id,
        workspace_grants=workspace_grants,
        workspace_denies=workspace_denies,
        workspace_delegable_grants=workspace_delegable_grants,
    )
    if not effective.can_delegate(action):
        raise PermissionError(
            f"principal {principal_id!r} cannot delegate {action!r} in Project {project_id!r}"
        )


async def authorize_membership_write(
    store: ProjectScopeStore,
    *,
    project: Project,
    workspace_store: WorkspaceStore,
    membership: ProjectMembership,
    principal_id: str | None,
    replacement: bool,
) -> None:
    """Authorize a Project membership grant at the store boundary (#1150).

    ADMINISTER (Workspace OWNER) may issue any grant or deny. A plain member
    may only add actions they can themselves delegate, and may not issue
    denies -- the same rule the HTTP route applies, resolved here so a caller
    that reaches the store directly cannot skip it. ``None`` is the
    internal/system shape; a blank principal is a refusal.

    ``replacement`` distinguishes the destructive `set_membership` upsert
    from the additive `merge_membership`: a replacement rewrites `role`,
    `grants`, `denies`, and `delegable_grants` wholesale, so holding a
    delegable action is not a sufficient credential for it (it would let a
    member erase an owner-issued deny with an empty set). Replacement writes
    therefore require ADMINISTER; only merges take the delegable path.
    """
    if principal_id is None:
        return

    from maistro.workspaces.store_boundary import (
        is_blank_principal,
        require_project_administer,
    )

    if is_blank_principal(principal_id):
        raise ProjectScopeDenied("Project not found")
    try:
        await require_project_administer(project, workspace_store, principal_id)
        return
    except ProjectScopeDenied:
        pass

    if replacement or membership.denies:
        raise ProjectScopeDenied("Project not found")
    for action in sorted(membership.grants | membership.delegable_grants):
        try:
            await require_delegable_grant(
                store,
                project_id=membership.project_id,
                principal_id=principal_id,
                action=action,
            )
        except PermissionError as exc:
            raise ProjectScopeDenied("Project not found") from exc


__all__ = [
    "EffectiveAuthorization",
    "authorize_membership_write",
    "require_delegable_grant",
    "resolve_project_authorization",
]
