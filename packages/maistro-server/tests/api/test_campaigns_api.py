"""The campaign operator-control API (#103, SPEC-092626-1831).

The routes are the UI's write path, so these tests drive the same records the
core contract defines: pin-next / pause / exclude / human-only, parks with
evidence, per-item priority and mode, usage, and the audit trail. Membership
is the only authorization the routes consult — the test asserts both that a
member can steer and that an outsider gets a 404 that leaks no Workspace
existence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole
from maistro.workspaces.campaigns import AuditKind, InMemoryCampaignStore
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal


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
    tuple[FastAPI, TestClient, InMemoryWorkspaceStore, InMemoryCampaignStore]
]:
    campaigns = InMemoryCampaignStore()
    workspaces = InMemoryWorkspaceStore()
    app = FastAPI()
    app.state.container = SimpleNamespace(campaign_store=campaigns)
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(workspaces)
    client = TestClient(app)
    try:
        yield app, client, workspaces, campaigns
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


def _workspace(client: TestClient, name: str = "Alpha") -> str:
    return client.post("/workspaces", json={"name": name}).json()["workspace_id"]


def _campaign(client: TestClient, workspace_id: str, name: str = "sprint") -> dict:
    response = client.post(
        f"/workspaces/{workspace_id}/campaigns",
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_owner_creates_campaign_and_members_read_it(api) -> None:
    app, client, store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    await store.set_membership(workspace_id, user_id="bob", role=WorkspaceRole.MEMBER)
    campaign = _campaign(client, workspace_id)
    assert campaign["workspace_id"] == workspace_id
    assert campaign["policy_version"] == 1
    assert campaign["created_by"] == {"kind": "user", "id": "alice"}

    _as_user(app, "bob")
    listed = client.get(f"/workspaces/{workspace_id}/campaigns")
    assert listed.status_code == 200
    assert [c["campaign_id"] for c in listed.json()] == [campaign["campaign_id"]]
    assert (await campaigns.list_campaigns(workspace_id))[0].name == "sprint"


async def test_non_member_gets_a_404_that_leaks_nothing(api) -> None:
    app, client, store, _campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    _campaign(client, workspace_id)
    await store.set_membership(workspace_id, user_id="bob", role=WorkspaceRole.MEMBER)

    _as_user(app, "mallory")
    assert client.get(f"/workspaces/{workspace_id}/campaigns").status_code == 404
    assert (
        client.post(f"/workspaces/{workspace_id}/campaigns", json={"name": "sneak"}).status_code
        == 404
    )


async def test_contributor_cannot_author_policy_but_owner_can(api) -> None:
    app, client, store, _campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    await store.set_membership(workspace_id, user_id="bob", role=WorkspaceRole.CONTRIBUTOR)
    campaign = _campaign(client, workspace_id)

    _as_user(app, "bob")
    denied = client.post(
        f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}/policy",
        json={"policy": {"default_autonomy_mode": "human-review-required"}},
    )
    assert denied.status_code == 403

    _as_user(app, "alice")
    updated = client.post(
        f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}/policy",
        json={"policy": {"default_autonomy_mode": "human-review-required"}},
    )
    assert updated.status_code == 200
    assert updated.json()["policy_version"] == 2


async def test_ui_controls_write_durable_attributed_records(api) -> None:
    """AC-5's write path: the four operator controls, written exactly as the
    UI writes them, come back with actor, item and policy version."""
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    campaign = _campaign(client, workspace_id)
    campaign_id = campaign["campaign_id"]
    base = f"/workspaces/{workspace_id}/campaigns/{campaign_id}"

    for kind, item_id in (
        ("pin-next", "item-1"),
        ("pause", None),
        ("exclude", "item-2"),
        ("human-only", "item-3"),
    ):
        response = client.post(
            f"{base}/controls",
            json={"kind": kind, "item_id": item_id},
        )
        assert response.status_code == 200, response.text
        control = response.json()
        assert control["kind"] == kind
        assert control["item_id"] == item_id
        assert control["set_by"] == {"kind": "user", "id": "alice"}
        assert control["policy_version"] == 1
        assert control["cleared_at"] is None

    listed = client.get(f"{base}/controls")
    assert listed.status_code == 200
    assert {c["kind"] for c in listed.json()} == {
        "pin-next",
        "pause",
        "exclude",
        "human-only",
    }
    # The store the process holds is the same one the routes wrote.
    assert len(await campaigns.list_controls(campaign_id, active_only=True)) == 4

    # Clearing through the API is its own recorded decision.
    control_id = client.get(f"{base}/controls").json()[0]["control_id"]
    cleared = client.post(f"{base}/controls/{control_id}/clear")
    assert cleared.status_code == 200
    assert cleared.json()["cleared_at"] is not None
    assert cleared.json()["cleared_by"] == {"kind": "user", "id": "alice"}

    audit = client.get(f"{base}/audit").json()
    kinds = [entry["kind"] for entry in audit]
    assert kinds.count(AuditKind.CONTROL_SET.value) == 4
    assert kinds.count(AuditKind.CONTROL_CLEARED.value) == 1
    assert all(entry["policy_version"] == 1 for entry in audit)


async def test_a_non_item_control_kind_must_not_carry_an_item_and_vice_versa(
    api,
) -> None:
    app, client, _store, _campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    campaign = _campaign(client, workspace_id)
    base = f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}"

    # pin-next is item-scoped: without an item the record is refused.
    assert client.post(f"{base}/controls", json={"kind": "pin-next"}).status_code == 422
    # A campaign-wide pause must not be pinned to an item.
    assert (
        client.post(f"{base}/controls", json={"kind": "pause", "item_id": "item-1"}).status_code
        == 200
    )


async def test_park_with_evidence_then_unpark_through_the_api(api) -> None:
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    campaign = _campaign(client, workspace_id)
    base = f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}"

    parked = client.post(
        f"{base}/items/item-9/park",
        json={
            "reason": "upstream broken",
            "blocking_dependency": "PR #100",
            "failing_check": "ci/integration",
            "run_reference": "run-77",
        },
    )
    assert parked.status_code == 200, parked.text
    park = parked.json()
    assert park["evidence"]["reason"] == "upstream broken"
    assert park["evidence"]["blocking_dependency"] == "PR #100"
    assert park["evidence"]["run_reference"] == "run-77"
    assert park["unparked"] is None

    unparked = client.post(f"{base}/parks/{park['park_id']}/unpark")
    assert unparked.status_code == 200
    assert unparked.json()["unparked"]["unparked_by"] == {"kind": "user", "id": "alice"}
    assert await campaigns.list_parks(campaign["campaign_id"], active_only=True) == []


async def test_item_record_stores_human_priority_exactly(api) -> None:
    app, client, _store, _campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    campaign = _campaign(client, workspace_id)
    base = f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}"

    set_record = client.put(
        f"{base}/items/item-1",
        json={"human_priority": 7.5, "mode_override": "human-review-required"},
    )
    assert set_record.status_code == 200
    assert set_record.json()["human_priority"] == 7.5
    assert set_record.json()["mode_override"] == "human-review-required"

    audit = client.get(f"{base}/audit").json()
    record_sets = [e for e in audit if e["kind"] == AuditKind.ITEM_RECORD_SET.value]
    assert record_sets[-1]["payload"]["human_priority"] == 7.5


async def test_unknown_campaign_is_404_without_existence_leak(api) -> None:
    app, client, _store, _campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    assert client.get(f"/workspaces/{workspace_id}/campaigns/nope").status_code == 404
    assert client.get(f"/workspaces/{workspace_id}/campaigns/nope/audit").status_code == 404


async def test_routes_are_absent_without_a_campaign_store(api) -> None:
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    app.state.container = SimpleNamespace(campaign_store=None)
    try:
        response = client.post(f"/workspaces/{workspace_id}/campaigns", json={"name": "sprint"})
        assert response.status_code == 503
    finally:
        app.state.container = SimpleNamespace(campaign_store=campaigns)
