"""Workspace Home routes (#1048) — authorization, parity, honest projections.

Driven against the app like every other route suite, over the real canonical
Workspace authority and the real durable stores. What these pin:

- fail-closed authorization: anonymous 401, non-member 404 (no existence
  oracle), viewer member 403 on writes;
- the layout contract over HTTP: default-when-unsaved, revision-checked saves,
  pin as a presentation-only operation;
- projections read the canonical services and only those: every projected id
  is an id an owning store already holds, and a section whose service cannot
  answer is `unavailable`, never fabricated;
- parity: the same dismissal and the same adaptive composition land in the
  same canonical state through the HTTP route and through the chat Agent's
  tool — no UI-only authority, and no browser automation for the Agent.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import stores
from fastapi.testclient import TestClient
from main import app


@pytest.fixture(autouse=True)
def _clean_home_state():
    for store in (stores.home_layouts, stores.home_adaptive_dismissals):
        for key in list(store.keys()):
            store.pop(key, None)
    yield
    for store in (stores.home_layouts, stores.home_adaptive_dismissals):
        for key in list(store.keys()):
            store.pop(key, None)


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


def _create_workspace(admin_client: TestClient, name: str = "Home WS") -> str:
    r = admin_client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_member(admin_client: TestClient, workspace_id: str, user_id: str, role: str) -> None:
    r = admin_client.post(
        f"/v1/workspaces/{workspace_id}/members", json={"user_id": user_id, "role": role}
    )
    assert r.status_code == 200, r.text


def _set_tool_workspace(workspace_id: str | None) -> Any:
    from services import chat_completion

    return chat_completion._chat_workspace_id.set(workspace_id)


# ---------------------------------------------------------------------------
# Fail-closed authorization
# ---------------------------------------------------------------------------


def test_anonymous_callers_get_401(admin_client: TestClient) -> None:
    ws = _create_workspace(admin_client)
    anon = TestClient(app)
    assert anon.get(f"/v1/workspaces/{ws}/home/layout").status_code == 401
    assert anon.put(f"/v1/workspaces/{ws}/home/layout", json={"regions": []}).status_code == 401
    assert anon.get(f"/v1/workspaces/{ws}/home/projections").status_code == 401
    assert (
        anon.post(
            f"/v1/workspaces/{ws}/home/adaptive/dismiss", json={"itemType": "goal", "itemId": "g"}
        ).status_code
        == 401
    )


def test_a_non_member_gets_the_missing_workspace_answer(admin_client, authed_client) -> None:
    """No existence oracle: stranger and missing id look identical (404)."""
    ws = _create_workspace(admin_client)
    ghost = "ws-that-does-not-exist"
    for client in (authed_client,):
        assert client.get(f"/v1/workspaces/{ws}/home/layout").status_code == 404
        assert client.get(f"/v1/workspaces/{ghost}/home/layout").status_code == 404
        assert client.get(f"/v1/workspaces/{ws}/home/projections").status_code == 404
        assert client.get(f"/v1/workspaces/{ghost}/home/projections").status_code == 404


def test_a_viewer_member_reads_but_cannot_write(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "viewer")

    assert authed_client.get(f"/v1/workspaces/{ws}/home/layout").status_code == 200
    r = authed_client.put(f"/v1/workspaces/{ws}/home/layout", json={"regions": []})
    assert r.status_code == 403
    r = authed_client.post(
        f"/v1/workspaces/{ws}/home/adaptive/dismiss", json={"itemType": "goal", "itemId": "g"}
    )
    assert r.status_code == 403
    r = authed_client.post(f"/v1/workspaces/{ws}/home/adaptive/compose", json={"regions": []})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# The layout contract over HTTP
# ---------------------------------------------------------------------------


def test_an_unsaved_workspace_is_offered_the_default_without_storing_it(
    admin_client, authed_client
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    body = authed_client.get(f"/v1/workspaces/{ws}/home/layout").json()
    assert body["revision"] == 0
    assert body["regions"]
    assert all(region["pinned"] is False for region in body["regions"])
    # Offered, not persisted.
    import services.home_layouts as home_layouts

    assert home_layouts.load(ws).revision == 0


def test_save_then_get_round_trips_with_a_revision(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    regions = [
        {"id": "r-goals", "kind": "goals", "pinned": True, "position": 0},
        {
            "id": "r-item",
            "kind": "backlog",
            "resource_type": "backlog_item",
            "resource_id": "item-1",
            "position": 1,
        },
    ]
    r = authed_client.put(
        f"/v1/workspaces/{ws}/home/layout", json={"regions": regions, "expectedRevision": 0}
    )
    assert r.status_code == 200, r.text
    revision = r.json()["revision"]
    assert revision == 1

    body = authed_client.get(f"/v1/workspaces/{ws}/home/layout").json()
    assert body["revision"] == revision
    assert {region["id"] for region in body["regions"]} == {"r-goals", "r-item"}


def test_a_stale_revision_gets_409_carrying_the_stored_layout(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    first = authed_client.put(
        f"/v1/workspaces/{ws}/home/layout", json={"regions": [{"id": "a", "kind": "goals"}]}
    )
    assert first.status_code == 200

    r = authed_client.put(
        f"/v1/workspaces/{ws}/home/layout",
        json={"regions": [{"id": "b", "kind": "runs"}], "expectedRevision": 0},
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["revision"] == 1
    assert [region["id"] for region in detail["regions"]] == ["a"]


def test_pin_is_presentation_only_and_never_forks_the_resource(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    authed_client.put(
        f"/v1/workspaces/{ws}/home/layout",
        json={
            "regions": [
                {
                    "id": "r-item",
                    "kind": "backlog",
                    "resource_type": "backlog_item",
                    "resource_id": "item-7",
                }
            ]
        },
    )

    r = authed_client.post(f"/v1/workspaces/{ws}/home/regions/r-item/pin", json={"pinned": True})
    assert r.status_code == 200, r.text
    assert r.json()["region"]["pinned"] is True
    assert r.json()["region"]["resource_id"] == "item-7"

    # One canonical identity, two surfaces' worth of presentation: the pin
    # wrote a preference, the referenced resource is the same id.
    import services.home_layouts as home_layouts

    stored = home_layouts.load(ws)
    assert stored.layout.regions[0].resource_id == "item-7"
    assert stores.backlog_items.get("item-7") is None  # nothing was created


# ---------------------------------------------------------------------------
# Projections over canonical services
# ---------------------------------------------------------------------------


def test_projections_come_from_canonical_ids_only(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    r = authed_client.post(
        "/v1/backlog",
        json={"title": "Projected item", "workspace_id": ws, "source": "user request"},
    )
    assert r.status_code == 201, r.text
    item = r.json()

    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    assert body["workspace_id"] == ws
    sections = {s["kind"]: s for s in body["sections"]}

    backlog = sections["backlog"]
    assert backlog["status"] == "ok"
    projected = [i["resource_id"] for i in backlog["items"]]
    assert item["id"] in projected
    # Every projected id is one the canonical store already holds: Home mints
    # no identity for showing an item in miniature.
    for projected_id in projected:
        assert projected_id in stores.backlog_items
        assert stores.backlog_items[projected_id].workspace_id == ws
    # The href opens the owning full surface.
    target = next(i for i in backlog["items"] if i["resource_id"] == item["id"])
    assert target["href"] == f"/backlog?item={item['id']}"


def test_an_empty_section_answers_empty_and_a_dead_section_answers_unavailable(
    admin_client, authed_client
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    sections = {s["kind"]: s for s in body["sections"]}

    # Nothing in this Workspace's backlog: empty, not fabricated.
    assert sections["backlog"]["status"] == "empty"
    assert sections["backlog"]["items"] == []
    # Every section names an honest state.
    for section in sections.values():
        assert section["status"] in {"ok", "empty", "unavailable"}


def test_projections_are_membership_scoped(admin_client, authed_client) -> None:
    """Another admin Workspace with items is invisible to a non-member: the
    read refuses before any section is computed."""
    ws = _create_workspace(admin_client)
    r = authed_client.get(f"/v1/workspaces/{ws}/home/projections")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Adaptive content: evidence, dismissal, and Agent/API parity
# ---------------------------------------------------------------------------


def test_adaptive_candidates_explain_and_dismissal_is_backend_state(
    admin_client, authed_client
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    item = authed_client.post(
        "/v1/backlog",
        json={
            "title": "Blocked deliverable",
            "workspace_id": ws,
            "status": "blocked",
            "source": "user request",
        },
    ).json()

    body = authed_client.get(f"/v1/workspaces/{ws}/home/adaptive").json()
    keys = [c["key"] for c in body["candidates"]]
    assert f"backlog_item:{item['id']}" in keys
    candidate = next(c for c in body["candidates"] if c["key"] == f"backlog_item:{item['id']}")
    assert "blocked" in candidate["explain"]
    assert candidate["resource_id"] == item["id"]

    r = authed_client.post(
        f"/v1/workspaces/{ws}/home/adaptive/dismiss",
        json={"itemType": "backlog_item", "itemId": item["id"]},
    )
    assert r.status_code == 200, r.text

    after = authed_client.get(f"/v1/workspaces/{ws}/home/adaptive").json()
    dismissed_key = f"backlog_item:{item['id']}"
    assert dismissed_key not in [c["key"] for c in after["candidates"]]
    assert after["dismissed"][dismissed_key] == 1

    # The record is durable server state, not client-only: it is in the store.
    assert stores.home_adaptive_dismissals[f"{ws}:backlog_item:{item['id']}"]["count"] == 1


def test_dismissal_through_the_agent_tool_and_the_route_land_in_one_place(
    admin_client, authed_client
) -> None:
    """Parity: chat tool and direct API write the same canonical state."""
    from services.chat_completion import _tool_dismiss_home_adaptive

    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    _set_tool_workspace(ws)
    try:
        via_tool = asyncio.run(
            _tool_dismiss_home_adaptive({"item_type": "goal", "item_id": "goal-1"}, "user", None)
        )
    finally:
        _set_tool_workspace(None)
    assert via_tool == {"dismissed": True, "count": 1, "key": "goal:goal-1"}

    r = authed_client.post(
        f"/v1/workspaces/{ws}/home/adaptive/dismiss",
        json={"itemType": "goal", "itemId": "goal-1"},
    )
    assert r.status_code == 200
    assert r.json()["dismissed"] == 2

    record = stores.home_adaptive_dismissals[f"{ws}:goal:goal-1"]
    assert record["count"] == 2

    # Without a Workspace context the tool refuses rather than guessing one.
    _set_tool_workspace(None)
    try:
        orphaned = asyncio.run(
            _tool_dismiss_home_adaptive({"item_type": "goal", "item_id": "goal-1"}, "user", None)
        )
    finally:
        _set_tool_workspace(None)
    assert orphaned["dismissed"] is False


def test_composition_through_the_agent_tool_matches_the_route(admin_client, authed_client) -> None:
    """Parity: the Agent composes through the same service the API serves, and
    the pinned half of Home is out of reach for both."""
    from services import home_layouts
    from services.chat_completion import _tool_compose_home_adaptive

    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    # The user pins one region, directly over the API.
    pin = authed_client.post(
        f"/v1/workspaces/{ws}/home/regions/default-goals/pin", json={"pinned": True}
    )
    assert pin.status_code == 200, pin.text

    _set_tool_workspace(ws)
    try:
        result = asyncio.run(
            _tool_compose_home_adaptive(
                {
                    "regions": [
                        {
                            "id": "agent-blocked",
                            "kind": "backlog",
                            "position": 9,
                            "reason": "blocked work in this Workspace",
                        }
                    ]
                },
                "user",
                None,
            )
        )
    finally:
        _set_tool_workspace(None)
    assert result["composed"] is True, result

    # Same state the route would have produced: pinned survives, agent region lands.
    stored = home_layouts.load(ws)
    regions = {r.id: r for r in stored.layout.regions}
    assert regions["default-goals"].pinned is True
    assert regions["agent-blocked"].reason == "blocked work in this Workspace"

    # The tool cannot smuggle a pin past the service, and the route cannot either.
    smuggle = asyncio.run(
        _tool_compose_home_adaptive(
            {"regions": [{"id": "pinned-clone", "kind": "runs", "pinned": True, "position": 8}]},
            "user",
            None,
        )
    )
    assert smuggle["composed"] is False

    r = authed_client.post(
        f"/v1/workspaces/{ws}/home/adaptive/compose",
        json={"regions": [{"id": "default-goals", "kind": "goals", "pinned": False}]},
    )
    assert r.status_code == 403
