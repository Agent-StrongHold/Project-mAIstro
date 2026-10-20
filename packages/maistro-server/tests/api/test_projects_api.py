from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.projects.scope import ProjectMembership
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal
from maistro_server.api.projects import (
    AddProjectMembershipBody,
    add_project_membership,
    remove_project_membership,
)
from maistro_server.api.route_table import iter_effective_routes
from maistro_server.main import app as server_app


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        token=f"token-{user_id}",
        roles=frozenset({"user"}),
    )


def _as_user(app: FastAPI, user_id: str) -> None:
    principal = _principal(user_id)
    app.dependency_overrides[verify_api_key] = lambda: principal


@pytest.fixture
async def api() -> AsyncIterator[
    tuple[FastAPI, TestClient, InMemoryWorkspaceStore, InMemoryProjectScopeStore]
]:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    app = FastAPI()
    app.state.container = SimpleNamespace(project_scope_store=projects)
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(workspaces)
    client = TestClient(app)
    try:
        yield app, client, workspaces, projects
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


async def test_owner_can_create_and_read_canonical_project_tree(api) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Alpha"}).json()["workspace_id"]

    root_response = client.get(f"/workspaces/{workspace_id}/projects/root")
    assert root_response.status_code == 200
    root = root_response.json()
    assert root["workspace_id"] == workspace_id
    assert root["is_root"] is True

    created_response = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={
            "parent_project_id": root["project_id"],
            "name": "Delivery",
            "defaults": {"model": "fast"},
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["parent_project_id"] == root["project_id"]

    fetched = client.get(f"/workspaces/{workspace_id}/projects/{created['project_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Delivery"

    children = client.get(f"/workspaces/{workspace_id}/projects/{root['project_id']}/children")
    assert children.status_code == 200
    assert [item["project_id"] for item in children.json()] == [created["project_id"]]


async def test_owner_can_update_defaults_and_move_project(api) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Tree"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()
    left = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"parent_project_id": root["project_id"], "name": "Left"},
    ).json()
    right = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"parent_project_id": root["project_id"], "name": "Right"},
    ).json()

    defaults = client.put(
        f"/workspaces/{workspace_id}/projects/{left['project_id']}/defaults",
        json={"defaults": {"model": "precise", "retries": 2}},
    )
    assert defaults.status_code == 200
    assert defaults.json()["defaults"] == {"model": "precise", "retries": 2}

    moved = client.patch(
        f"/workspaces/{workspace_id}/projects/{left['project_id']}/parent",
        json={"parent_project_id": right["project_id"]},
    )
    assert moved.status_code == 200
    assert moved.json()["parent_project_id"] == right["project_id"]
    assert moved.json()["defaults"] == {"model": "precise", "retries": 2}


async def test_non_member_cannot_discover_project_or_root(api) -> None:
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Private")
    root = await projects.root_for_workspace(workspace.workspace_id)
    child = await projects.create(
        workspace_id=workspace.workspace_id,
        parent_project_id=root.project_id,
        name="Hidden",
    )
    _as_user(app, "mallory")

    assert client.get(f"/workspaces/{workspace.workspace_id}/projects/root").status_code == 404
    assert (
        client.get(f"/workspaces/{workspace.workspace_id}/projects/{child.project_id}").status_code
        == 404
    )


async def test_cross_workspace_project_id_is_hidden(api) -> None:
    app, client, workspaces, projects = api
    first = await workspaces.create(creator_user_id="alice", name="First")
    second = await workspaces.create(creator_user_id="alice", name="Second")
    second_root = await projects.root_for_workspace(second.workspace_id)
    _as_user(app, "alice")

    response = client.get(f"/workspaces/{first.workspace_id}/projects/{second_root.project_id}")

    assert response.status_code == 404


async def test_cross_workspace_project_id_is_hidden_from_a_foreign_member(api) -> None:
    """A member of one Workspace cannot reach another's Project id (#1150).

    The store resolves Project scope against the acting principal, so a
    Project in a Workspace the caller does not belong to is refused at the
    boundary. The route must answer that refusal the way it answers an
    unknown id -- a 404 -- rather than surfacing the store's denial.
    """
    app, client, workspaces, projects = api
    first = await workspaces.create(creator_user_id="alice", name="First")
    second = await workspaces.create(creator_user_id="bob", name="Second")
    second_root = await projects.root_for_workspace(second.workspace_id)
    # alice owns `first` only; bob owns `second`.
    _as_user(app, "alice")

    response = client.get(f"/workspaces/{first.workspace_id}/projects/{second_root.project_id}")

    assert response.status_code == 404


async def test_cross_workspace_parent_is_hidden_and_cannot_create_child(api) -> None:
    app, client, workspaces, projects = api
    first = await workspaces.create(creator_user_id="alice", name="First")
    second = await workspaces.create(creator_user_id="alice", name="Second")
    second_root = await projects.root_for_workspace(second.workspace_id)
    _as_user(app, "alice")

    response = client.post(
        f"/workspaces/{first.workspace_id}/projects",
        json={"parent_project_id": second_root.project_id, "name": "Crossed"},
    )

    assert response.status_code == 404
    assert await projects.list_children(second_root.project_id) == []


async def test_contributor_can_read_but_cannot_mutate_structure(api) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Shared"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()
    assert (
        client.put(
            f"/workspaces/{workspace_id}/members/bob",
            json={"role": "contributor"},
        ).status_code
        == 200
    )

    _as_user(app, "bob")
    assert client.get(f"/workspaces/{workspace_id}/projects/root").status_code == 200
    forbidden = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"parent_project_id": root["project_id"], "name": "Nope"},
    )
    assert forbidden.status_code == 403


async def test_illegal_project_move_fails_closed_without_mutation(api) -> None:
    app, client, _workspaces, projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Tree"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()
    parent = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"parent_project_id": root["project_id"], "name": "Parent"},
    ).json()
    child = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"parent_project_id": parent["project_id"], "name": "Child"},
    ).json()

    response = client.patch(
        f"/workspaces/{workspace_id}/projects/{parent['project_id']}/parent",
        json={"parent_project_id": child["project_id"]},
    )

    assert response.status_code == 409
    unchanged = await projects.get(parent["project_id"])
    assert unchanged is not None
    assert unchanged.parent_project_id == root["project_id"]


async def test_root_project_delete_is_refused(api) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Tree"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()

    response = client.delete(f"/workspaces/{workspace_id}/projects/{root['project_id']}")

    assert response.status_code == 409
    assert "Root Project cannot be deleted" in response.json()["detail"]


async def test_non_empty_project_delete_is_refused(api) -> None:
    app, client, _workspaces, projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Tree"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()
    parent = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"parent_project_id": root["project_id"], "name": "Parent"},
    ).json()
    await projects.create(
        workspace_id=workspace_id,
        parent_project_id=parent["project_id"],
        name="Child",
    )

    response = client.delete(f"/workspaces/{workspace_id}/projects/{parent['project_id']}")

    assert response.status_code == 409
    assert "child Projects" in response.json()["detail"]


async def test_non_owner_cannot_grant_action_without_delegation(api) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Auth"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()
    client.put(f"/workspaces/{workspace_id}/members/bob", json={"role": "contributor"})

    _as_user(app, "bob")
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{root['project_id']}/memberships",
        json={"principal_id": "cara", "grants": ["publish"]},
    )

    assert response.status_code == 403
    assert "cannot delegate" in response.json()["detail"]


async def test_delegable_project_grant_allows_non_owner_to_delegate(api) -> None:
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish"},
            delegable_grants={"publish"},
        )
    )
    _as_user(app, "bob")

    response = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships",
        json={"principal_id": "cara", "grants": ["publish"]},
    )

    assert response.status_code == 201
    assert response.json()["principal_id"] == "cara"
    assert response.json()["grants"] == ["publish"]


async def test_inherited_deny_blocks_delegation_even_below_new_grant(api) -> None:
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    child = await projects.create(
        workspace_id=workspace.workspace_id,
        parent_project_id=root.project_id,
        name="Child",
    )
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish"},
            denies={"publish"},
        )
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=child.project_id,
            principal_id="bob",
            grants={"publish"},
            delegable_grants={"publish"},
        )
    )
    _as_user(app, "bob")

    response = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{child.project_id}/memberships",
        json={"principal_id": "cara", "grants": ["publish"]},
    )

    assert response.status_code == 403
    assert "cannot delegate" in response.json()["detail"]


async def test_only_workspace_owner_can_issue_project_denies(api) -> None:
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish"},
            delegable_grants={"publish"},
        )
    )

    _as_user(app, "bob")
    refused = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships",
        json={"principal_id": "cara", "grants": ["publish"], "denies": ["publish"]},
    )
    assert refused.status_code == 403

    _as_user(app, "alice")
    accepted = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships",
        json={"principal_id": "cara", "grants": ["publish"], "denies": ["publish"]},
    )
    assert accepted.status_code == 201
    listed = client.get(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships"
    )
    assert listed.status_code == 200
    assert any(item["principal_id"] == "cara" for item in listed.json())


async def test_non_owner_cannot_delegate_a_non_delegable_action_via_regrant(api) -> None:
    """A held action is not a delegable one, even re-granted with the flag (#1150).

    Bob holds ``publish`` at this Project without the delegable flag. The
    escalation attempt is to re-grant it to cara *with* ``delegable_grants``
    so cara can re-delegate further. The body validator forces the action
    into ``grants`` too, and both the route's pre-check and the store's
    boundary authorization answer that holding is not delegating: 403, and
    nothing stored.
    """
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish"},
        )
    )
    _as_user(app, "bob")

    response = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships",
        json={
            "principal_id": "cara",
            "grants": ["publish"],
            "delegable_grants": ["publish"],
        },
    )

    assert response.status_code == 403
    assert "cannot delegate" in response.json()["detail"]
    assert await projects.memberships_for(root.project_id, principal_id="cara") == []


async def test_a_revocation_landing_after_the_pre_check_is_not_a_500(api, monkeypatch) -> None:
    """A membership-write refusal after the pre-check is a 403, not a 500 (#1150).

    The store's membership-write boundary re-resolves the requester's
    delegable grants itself. An owner's revocation landing between the
    route's pre-check and that boundary check makes the store refuse with
    `ProjectScopeDenied` -- which this route must render as its own 403,
    the same answer the pre-check would have given, rather than let escape
    as an unhandled exception.
    """
    from maistro_server.api import projects as projects_api

    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id, user_id="bob", role=WorkspaceRole.CONTRIBUTOR
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish"},
            delegable_grants={"publish"},
        ),
        principal_id="alice",
    )
    _as_user(app, "bob")

    async def _revocation_lands_after_the_pre_check(*args: object, **kwargs: object) -> None:
        # The owner's revocation commits between the route's pre-check and
        # the store's boundary authorization: the pre-check saw the
        # delegable grant, the boundary below must refuse without it.
        await projects.remove_membership(
            root.project_id, principal_id="bob", acting_principal_id="alice"
        )

    monkeypatch.setattr(
        projects_api, "require_delegable_grant", _revocation_lands_after_the_pre_check
    )

    response = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships",
        json={"principal_id": "cara", "grants": ["publish"]},
    )

    assert response.status_code == 403
    assert "cannot delegate" in response.json()["detail"]
    assert await projects.memberships_for(root.project_id, principal_id="cara") == []


async def test_an_ownership_loss_racing_a_membership_removal_is_not_a_500(api, monkeypatch) -> None:
    """A membership-removal refusal at the boundary is a 403, not a 500 (#1150).

    ``remove_membership`` re-resolves the requester's ADMINISTER authority in
    the store. Ownership revoked between the route's owner check and that
    boundary check must render as the route's owner-permission 403, not
    escape as an unhandled `ProjectScopeDenied`.
    """
    from maistro_server.api import projects as projects_api

    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(workspace.workspace_id, user_id="bob", role=WorkspaceRole.OWNER)
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="cara",
            grants={"publish"},
        ),
        principal_id="alice",
    )
    _as_user(app, "alice")

    async def _ownership_revoked_after_the_route_check(*args: object, **kwargs: object) -> None:
        # A co-owner demotes the requester between the route's owner check
        # and the store's boundary authorization.
        await workspaces.set_membership(
            workspace.workspace_id, user_id="alice", role=WorkspaceRole.CONTRIBUTOR
        )

    monkeypatch.setattr(
        projects_api,
        "require_workspace_owner",
        _ownership_revoked_after_the_route_check,
    )

    response = client.delete(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships/cara"
    )

    assert response.status_code == 403
    assert "Workspace owner permission required" in response.json()["detail"]
    memberships = await projects.memberships_for(root.project_id, principal_id="cara")
    assert memberships and memberships[0].grants == {"publish"}


async def test_workspace_owner_can_revoke_a_project_membership(api) -> None:
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="cara",
            grants={"publish"},
        )
    )
    _as_user(app, "alice")

    response = client.delete(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships/cara"
    )

    assert response.status_code == 204
    assert await projects.memberships_for(root.project_id, principal_id="cara") == []


async def test_non_owner_cannot_revoke_a_project_membership(api) -> None:
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="cara",
            grants={"publish"},
        )
    )
    _as_user(app, "bob")

    response = client.delete(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships/cara"
    )

    assert response.status_code == 403
    assert len(await projects.memberships_for(root.project_id, principal_id="cara")) == 1


async def test_a_non_owner_delegated_regrant_cannot_clear_an_existing_deny(api) -> None:
    """`set_membership` upserts the one canonical row per (project, principal)
    -- correct per #1148 -- so a request that omits `denies` must not be read
    as "clear whatever denies exist," or a non-owner could launder away an
    owner-issued deny simply by never repeating it back."""
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish", "read"},
            delegable_grants={"read"},
        )
    )
    # Owner denies "cara" publish rights at this Project.
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="cara",
            denies={"publish"},
        )
    )

    _as_user(app, "bob")
    response = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships",
        json={"principal_id": "cara", "grants": ["read"]},
    )

    assert response.status_code == 201
    assert response.json()["denies"] == ["publish"]
    memberships = await projects.memberships_for(root.project_id, principal_id="cara")
    assert memberships[0].denies == {"publish"}
    assert memberships[0].grants == {"read"}


async def test_a_non_owner_delegated_regrant_preserves_owner_issued_authority(api) -> None:
    """The same upsert logic applies to the whole canonical row (#1148): a
    non-owner's delegated POST adds authority the requester can delegate, but
    must not replace owner-issued grants, delegable authority, or role.
    Reproduced from review: owner-issued grants=['publish'],
    delegable_grants=['publish'] were erased by a delegated POST carrying only
    grants=['read'], returning 201 grants=['read'], delegable_grants=[] with no
    owner revocation anywhere."""
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish", "read"},
            delegable_grants={"read"},
        )
    )
    # Owner grants "cara" publish authority, delegation of it, and a role.
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="cara",
            role="editor",
            grants={"publish"},
            delegable_grants={"publish"},
        )
    )

    _as_user(app, "bob")
    response = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships",
        json={"principal_id": "cara", "grants": ["read"], "delegable_grants": ["read"]},
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body["grants"]) == {"publish", "read"}
    assert set(body["delegable_grants"]) == {"publish", "read"}
    assert body["role"] == "editor"
    memberships = await projects.memberships_for(root.project_id, principal_id="cara")
    assert len(memberships) == 1
    assert memberships[0].grants == {"publish", "read"}
    assert memberships[0].delegable_grants == {"publish", "read"}
    assert memberships[0].role == "editor"


async def test_a_non_owner_delegated_post_cannot_grant_beyond_own_delegation(api) -> None:
    """Merging must not become an escalation path: an action absent from the
    stored row still requires the requester to hold it as delegable."""
    app, client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish", "read"},
            delegable_grants={"read"},
        )
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="cara",
            grants={"read"},
        )
    )

    _as_user(app, "bob")
    response = client.post(
        f"/workspaces/{workspace.workspace_id}/projects/{root.project_id}/memberships",
        json={"principal_id": "cara", "grants": ["read", "publish"]},
    )

    assert response.status_code == 403
    memberships = await projects.memberships_for(root.project_id, principal_id="cara")
    assert memberships[0].grants == {"read"}


async def test_owner_revocation_racing_a_delegated_regrant_cannot_resurrect_the_revoked_principal(
    api,
    monkeypatch,
) -> None:
    """Reproduced from review: a delegated POST read the target principal's
    membership with `memberships_for` and merged it in Python before writing
    through `set_membership`, so an owner revocation committing between the
    read and the write was overwritten by an upsert "preserving" the stale
    row -- Cara came back holding grants=['publish','read'] after the owner
    had revoked her. The merge is now one atomic store operation decided
    inside the store's critical section, so a revocation that commits first
    leaves nothing to preserve: the re-granted row carries only what the
    requester could actually delegate."""
    _app, _client, workspaces, projects = api
    workspace = await workspaces.create(creator_user_id="alice", name="Auth")
    root = await projects.root_for_workspace(workspace.workspace_id)
    await workspaces.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="bob",
            grants={"read"},
            delegable_grants={"read"},
        )
    )
    # Owner-issued authority for Cara, about to be revoked concurrently.
    await projects.set_membership(
        ProjectMembership(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            principal_id="cara",
            grants={"publish"},
        )
    )

    real_merge = projects.merge_membership
    real_remove = projects.remove_membership
    revoked = asyncio.Event()

    async def revocation_lands_first(
        project_id: str,
        *,
        principal_id: str,
        acting_principal_id: str | None = None,
    ) -> None:
        await real_remove(
            project_id,
            principal_id=principal_id,
            acting_principal_id=acting_principal_id,
        )
        revoked.set()

    async def merge_only_after_revocation(
        membership: ProjectMembership,
        *,
        principal_id: str | None = None,
    ) -> ProjectMembership:
        await revoked.wait()
        return await real_merge(membership, principal_id=principal_id)

    monkeypatch.setattr(projects, "remove_membership", revocation_lands_first)
    monkeypatch.setattr(projects, "merge_membership", merge_only_after_revocation)

    granted, _ = await asyncio.gather(
        add_project_membership(
            workspace.workspace_id,
            root.project_id,
            AddProjectMembershipBody(principal_id="cara", grants={"read"}),
            auth=_principal("bob"),
            workspace_store=workspaces,
            project_store=projects,
        ),
        remove_project_membership(
            workspace.workspace_id,
            root.project_id,
            "cara",
            auth=_principal("alice"),
            workspace_store=workspaces,
            project_store=projects,
        ),
    )

    assert granted.grants == {"read"}
    memberships = await projects.memberships_for(root.project_id, principal_id="cara")
    assert len(memberships) == 1
    assert memberships[0].grants == {"read"}
    assert memberships[0].denies == set()


@pytest.mark.parametrize("field", ["name", "parent_project_id"])
async def test_blank_project_create_identity_fields_are_rejected_before_route_logic(
    api, field: str
) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Auth"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()
    body = {"parent_project_id": root["project_id"], "name": "Child"}
    body[field] = "   "

    response = client.post(f"/workspaces/{workspace_id}/projects", json=body)

    assert response.status_code == 422


async def test_blank_project_membership_principal_is_rejected_before_route_logic(api) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Auth"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()

    response = client.post(
        f"/workspaces/{workspace_id}/projects/{root['project_id']}/memberships",
        json={"principal_id": "   ", "grants": ["publish"]},
    )

    assert response.status_code == 422


async def test_invalid_delegable_grant_shape_is_rejected_before_route_logic(api) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Auth"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()

    response = client.post(
        f"/workspaces/{workspace_id}/projects/{root['project_id']}/memberships",
        json={"principal_id": "cara", "delegable_grants": ["publish"]},
    )

    assert response.status_code == 422


async def test_blank_permission_action_is_rejected_before_route_logic(api) -> None:
    app, client, _workspaces, _projects = api
    _as_user(app, "alice")
    workspace_id = client.post("/workspaces", json={"name": "Auth"}).json()["workspace_id"]
    root = client.get(f"/workspaces/{workspace_id}/projects/root").json()

    response = client.post(
        f"/workspaces/{workspace_id}/projects/{root['project_id']}/memberships",
        json={"principal_id": "cara", "grants": [" "]},
    )

    assert response.status_code == 422


def test_production_app_mounts_project_routes_at_v1_and_legacy_paths() -> None:
    paths = {route.path for route in iter_effective_routes(server_app.routes)}
    assert "/v1/workspaces/{workspace_id}/projects/root" in paths
    assert "/workspaces/{workspace_id}/projects/root" in paths


async def test_project_routes_fail_closed_without_container_store() -> None:
    app = FastAPI()
    app.include_router(workspace_api.router)
    workspaces = InMemoryWorkspaceStore()
    workspace_api.configure_workspace_store(workspaces)
    workspace = await workspaces.create(creator_user_id="alice", name="No container")
    _as_user(app, "alice")
    client = TestClient(app)
    try:
        response = client.get(f"/workspaces/{workspace.workspace_id}/projects/root")
        assert response.status_code == 503
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)
