"""Shared scope enforcement at durable store boundaries (#364)."""

from __future__ import annotations

from typing import Any

from maistro.projects.scope import Project, ProjectScopeDenied
from maistro.workspaces.authorization import (
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
    decide_workspace_action,
)
from maistro.workspaces.model import WorkspaceMembership, WorkspaceNotFound
from maistro.workspaces.store import WorkspaceStore


def is_blank_principal(principal_id: object) -> bool:
    return not isinstance(principal_id, str) or not principal_id.strip()


async def require_workspace_view(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    principal_id: str,
) -> None:
    await WorkspaceAuthorizer(workspace_store).require(
        principal_id, workspace_id, WorkspaceAction.VIEW
    )


async def require_workspace_administer(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    principal_id: str,
) -> None:
    await WorkspaceAuthorizer(workspace_store).require(
        principal_id, workspace_id, WorkspaceAction.ADMINISTER
    )


async def authorize_workspace_view(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    principal_id: str | None,
) -> None:
    """Enforce VIEW when the caller supplied an acting principal.

    ``None`` is the explicit internal/system call shape used by bootstrap and
    migration code that owns the store rather than acting for a user. Product
    consumers always carry a principal, so they cannot take this branch by
    accident (#1150). A blank principal is a refusal, not an absent one.
    """
    if principal_id is None:
        return
    if is_blank_principal(principal_id):
        raise WorkspaceAuthorizationDenied
    await require_workspace_view(workspace_store, workspace_id, principal_id)


async def authorize_workspace_administer(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    principal_id: str | None,
) -> None:
    """Enforce ADMINISTER when the caller supplied an acting principal."""
    if principal_id is None:
        return
    if is_blank_principal(principal_id):
        raise WorkspaceAuthorizationDenied
    await require_workspace_administer(workspace_store, workspace_id, principal_id)


def membership_removal_action(user_id: str, principal_id: str) -> WorkspaceAction:
    """The action a membership removal needs.

    Leaving a Workspace is deliberately not an owner-only action, so a
    principal removing themselves needs VIEW; removing anyone else needs
    ADMINISTER. Both the pre-write check and the in-transaction re-check ask
    this, so the self-service exception cannot become two rules.
    """
    return WorkspaceAction.VIEW if principal_id == user_id else WorkspaceAction.ADMINISTER


async def authorize_membership_removal(
    workspace_store: WorkspaceStore,
    workspace_id: str,
    *,
    user_id: str,
    principal_id: str | None,
) -> None:
    """Authorize removing ``user_id``'s membership as ``principal_id``.

    Leaving a Workspace is deliberately not an owner-only action, so a
    principal removing themselves needs VIEW; removing anyone else needs
    ADMINISTER. Both answers still come from `WorkspaceAuthorizer`, so the
    self-service exception cannot become a second authorization path.
    """
    if principal_id is None:
        return
    if is_blank_principal(principal_id):
        raise WorkspaceAuthorizationDenied
    if membership_removal_action(user_id, principal_id) is WorkspaceAction.VIEW:
        await require_workspace_view(workspace_store, workspace_id, principal_id)
        return
    await require_workspace_administer(workspace_store, workspace_id, principal_id)


async def require_workspace_action_on(
    workspace_store: WorkspaceStore,
    conn: Any,
    workspace_id: str,
    principal_id: str | None,
    action: WorkspaceAction,
) -> WorkspaceMembership | None:
    """Re-decide a Workspace action on the connection that will do the write.

    The check a store runs before its write is a fast refusal, not the
    decision: an owner demoted between that check and the write's lock
    could still write, because the check had read a roster that was already
    stale (#1150). This asks the same question again on the *writing*
    connection, after the Workspace's own serialization point has been
    taken, so the read that decides is serialized with the revocation it
    races.

    The decision is `decide_workspace_action` -- the same function
    `WorkspaceAuthorizer.require` uses -- so there is still exactly one
    rule, and the re-check cannot drift from it.
    """
    if principal_id is None:
        return None
    if is_blank_principal(principal_id):
        raise WorkspaceAuthorizationDenied
    membership = await workspace_store.lock_and_read_membership(
        conn, workspace_id, user_id=principal_id
    )
    return decide_workspace_action(membership, action)


async def require_membership_removal_on(
    workspace_store: WorkspaceStore,
    conn: Any,
    workspace_id: str,
    *,
    user_id: str,
    principal_id: str | None,
) -> None:
    """Re-decide a membership removal on the connection that will do the write.

    Mirrors `authorize_membership_removal` exactly: the same action, the
    same decision function, read under the same lock (#1150).
    """
    if principal_id is None:
        return
    if is_blank_principal(principal_id):
        raise WorkspaceAuthorizationDenied
    action = membership_removal_action(user_id, principal_id)
    await require_workspace_action_on(workspace_store, conn, workspace_id, principal_id, action)


async def require_project_view(
    project: Project,
    workspace_store: WorkspaceStore,
    principal_id: str,
) -> None:
    if is_blank_principal(principal_id):
        raise ProjectScopeDenied("Project not found")
    try:
        await require_workspace_view(workspace_store, project.workspace_id, principal_id)
    except WorkspaceAuthorizationDenied as exc:
        raise ProjectScopeDenied("Project not found") from exc


async def require_project_administer(
    project: Project,
    workspace_store: WorkspaceStore,
    principal_id: str,
) -> None:
    """Require Workspace ADMINISTER for a Project-scoped write.

    A Project's authority is its Workspace's: there is no second Project
    owner role to resolve. Missing, foreign and blank-principal cases all
    read as one `ProjectScopeDenied`, so a refusal never discloses that a
    Project id exists (#1150).
    """
    if is_blank_principal(principal_id):
        raise ProjectScopeDenied("Project not found")
    try:
        await require_workspace_administer(workspace_store, project.workspace_id, principal_id)
    except WorkspaceAuthorizationDenied as exc:
        raise ProjectScopeDenied("Project not found") from exc


async def require_project_administer_on(
    project: Project,
    workspace_store: WorkspaceStore,
    conn: Any,
    principal_id: str,
) -> None:
    """Require Workspace ADMINISTER for a Project write, on the writing connection.

    The refusal is the same `ProjectScopeDenied("Project not found")` the
    pre-write check raises, so a Project id is still not disclosed to a
    principal who lost the authority between the check and the write
    (#1150).
    """
    try:
        await require_workspace_action_on(
            workspace_store,
            conn,
            project.workspace_id,
            principal_id,
            WorkspaceAction.ADMINISTER,
        )
    except (WorkspaceAuthorizationDenied, WorkspaceNotFound) as exc:
        raise ProjectScopeDenied("Project not found") from exc


__all__ = [
    "ProjectScopeDenied",
    "WorkspaceAuthorizationDenied",
    "authorize_membership_removal",
    "authorize_workspace_administer",
    "authorize_workspace_view",
    "is_blank_principal",
    "membership_removal_action",
    "require_membership_removal_on",
    "require_project_administer",
    "require_project_administer_on",
    "require_project_view",
    "require_workspace_action_on",
    "require_workspace_administer",
    "require_workspace_view",
]
