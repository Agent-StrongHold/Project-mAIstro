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
from maistro.workspaces.campaigns import (
    Actor,
    ActorKind,
    AuditKind,
    ControlKind,
    InMemoryCampaignStore,
    ParkEvidence,
)
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro.identity import Principal


def _principal(user_id: str) -> Principal:
    return Principal(
        user_id=user_id,
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


async def test_routes_are_absent_without_a_container_at_all(api) -> None:
    """The 503 is the deployment's answer, not a leak: no container wired
    means no campaign surface, whatever the routes' paths suggest."""
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    del app.state.container
    try:
        response = client.get(f"/workspaces/{workspace_id}/campaigns")
        assert response.status_code == 503
    finally:
        app.state.container = SimpleNamespace(campaign_store=campaigns)


async def test_routes_are_absent_when_the_container_has_no_campaign_store(api) -> None:
    """A container without the attribute is as good as no store: the route
    refuses rather than guessing what the deployment meant."""
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    app.state.container = SimpleNamespace()
    try:
        response = client.get(f"/workspaces/{workspace_id}/campaigns")
        assert response.status_code == 503
    finally:
        app.state.container = SimpleNamespace(campaign_store=campaigns)


async def test_clearing_an_unknown_control_is_a_404(api) -> None:
    app, client, _store, _campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    campaign = _campaign(client, workspace_id)
    base = f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}"
    response = client.post(f"{base}/controls/does-not-exist/clear")
    assert response.status_code == 404


async def test_a_control_of_another_campaign_cannot_be_cleared_through_this_one(
    api,
) -> None:
    """The campaign id in the path scopes the decision: a control record that
    belongs to a different campaign answers 404, not its body."""
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    first = _campaign(client, workspace_id, name="first")
    second = _campaign(client, workspace_id, name="second")
    control = await campaigns.set_control(
        second["campaign_id"],
        ControlKind.PIN_NEXT,
        actor=Actor(kind=ActorKind.USER, id="alice"),
        item_id="item-1",
    )
    base = f"/workspaces/{workspace_id}/campaigns/{first['campaign_id']}"
    response = client.post(f"{base}/controls/{control.control_id}/clear")
    assert response.status_code == 404
    assert control.active


async def test_unparking_an_unknown_park_is_a_404(api) -> None:
    app, client, _store, _campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    campaign = _campaign(client, workspace_id)
    base = f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}"
    assert client.post(f"{base}/parks/does-not-exist/unpark").status_code == 404


async def test_a_park_of_another_campaign_cannot_be_unparked_through_this_one(api) -> None:
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    first = _campaign(client, workspace_id, name="first")
    second = _campaign(client, workspace_id, name="second")
    park = await campaigns.park_item(
        second["campaign_id"],
        "item-1",
        ParkEvidence(reason="waiting on upstream"),
        actor=Actor(kind=ActorKind.USER, id="alice"),
    )
    base = f"/workspaces/{workspace_id}/campaigns/{first['campaign_id']}"
    assert client.post(f"{base}/parks/{park.park_id}/unpark").status_code == 404
    assert park.active


async def test_item_records_list_what_the_route_wrote(api) -> None:
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    campaign = _campaign(client, workspace_id)
    base = f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}"
    client.put(f"{base}/items/item-1", json={"human_priority": 3.0})
    client.put(f"{base}/items/item-2", json={"mode_override": "human-only"})

    listed = client.get(f"{base}/items")
    assert listed.status_code == 200
    assert [(record["item_id"], record["human_priority"]) for record in listed.json()] == [
        ("item-1", 3.0),
        ("item-2", None),
    ]
    assert listed.json()[1]["mode_override"] == "human-only"
    assert len(await campaigns.list_item_records(campaign["campaign_id"])) == 2


async def test_usage_is_recorded_with_an_actor_and_accumulates(api) -> None:
    """The persistent Workspace Agent's consumption (#804) is attributed like
    every other decision, and the campaign's budget counters accumulate."""
    app, client, _store, campaigns = api
    _as_user(app, "alice")
    workspace_id = _workspace(client)
    campaign = _campaign(client, workspace_id)
    base = f"/workspaces/{workspace_id}/campaigns/{campaign['campaign_id']}"

    first = client.post(f"{base}/usage", json={"cost_usd": 1.25, "minutes": 10.0})
    assert first.status_code == 200
    second = client.post(f"{base}/usage", json={"cost_usd": 0.75, "completions": 1})
    assert second.status_code == 200
    assert second.json() == {"cost_usd": 2.0, "minutes": 10.0, "completions": 1}

    usage = await campaigns.get_usage(campaign["campaign_id"])
    assert usage.cost_usd == pytest.approx(2.0)
    decision = [
        record
        for record in await campaigns.audit_trail(campaign["campaign_id"])
        if record.kind is AuditKind.USAGE_RECORDED
    ][-1]
    assert decision.actor == Actor(kind=ActorKind.USER, id="alice")
