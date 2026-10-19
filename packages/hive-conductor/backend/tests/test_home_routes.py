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
from datetime import UTC, datetime
from typing import Any

import pytest
import stores
from fastapi.testclient import TestClient
from main import app
from services import home_layouts, home_projections


@pytest.fixture(autouse=True)
def _clean_home_state():
    for store in (home_layouts.layout_store, home_projections.dismissal_store):
        for key in list(store.keys()):
            store.pop(key, None)
    yield
    for store in (home_layouts.layout_store, home_projections.dismissal_store):
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


def test_the_goals_section_names_its_unavailable_rather_than_reading_the_retiring_store(
    admin_client, authed_client
) -> None:
    """The only Goal rows in this backend live in `stores.missions`, a surface
    the cutover retirement ledger (#1046) froze to new consumers — and Home's
    projection reader is exactly the consumer the freeze exists to stop. The
    section must therefore say why it cannot answer even when Goal rows sit
    right there, and the adaptive half must offer no Goal candidate sourced
    from them: an honest `unavailable` is the contract, a plausible projection
    off a retiring store is the bug.
    """
    from models.schemas import Mission

    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    # The temptation this test pins the refusal against: rows that would
    # project perfectly well if the reader reached for the retiring store.
    t = datetime.now(UTC)
    stores.missions["home-goal-seed"] = Mission(
        id="home-goal-seed",
        user_id="user",
        name="A goal Home must not project from the retiring store",
        description="present, but not Home's to read",
        status="pending",
        priority="medium",
        created_at=t,
        updated_at=t,
        assigned_agents=[],
        tags=[],
        metadata={},
    )
    try:
        body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
        sections = {s["kind"]: s for s in body["sections"]}
        goals = sections["goals"]
        assert goals["status"] == "unavailable"
        assert goals["items"] == []
        assert "canonical Goal service" in goals["reason"]
        assert "home-goal-seed" not in body_text_of(goals)

        adaptive = authed_client.get(f"/v1/workspaces/{ws}/home/adaptive").json()
        assert all(c["item_type"] != "goal" for c in adaptive["candidates"])
    finally:
        stores.missions.pop("home-goal-seed", None)


def body_text_of(section: dict[str, Any]) -> str:
    """Everything the section could leak a projected id through."""
    import json

    return json.dumps(section)


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
    assert home_projections.dismissal_store[f"{ws}:backlog_item:{item['id']}"]["count"] == 1


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

    record = home_projections.dismissal_store[f"{ws}:goal:goal-1"]
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

    # The tool cannot smuggle a pin past the service, and the route cannot
    # either. The compose happens INSIDE the turn's Workspace context, so the
    # refusal this asserts is the pinned-write refusal — not the missing
    # Workspace one the context reset would otherwise produce.
    _set_tool_workspace(ws)
    try:
        smuggle = asyncio.run(
            _tool_compose_home_adaptive(
                {
                    "regions": [
                        {"id": "pinned-clone", "kind": "runs", "pinned": True, "position": 8}
                    ]
                },
                "user",
                None,
            )
        )
    finally:
        _set_tool_workspace(None)
    assert smuggle["composed"] is False
    assert "pinned" in smuggle["error"]

    r = authed_client.post(
        f"/v1/workspaces/{ws}/home/adaptive/compose",
        json={"regions": [{"id": "default-goals", "kind": "goals", "pinned": False}]},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Failure honesty: persistence faults, invalid payloads, defense in depth
# ---------------------------------------------------------------------------


def test_a_layout_that_cannot_be_persisted_answers_503(
    admin_client, authed_client, monkeypatch
) -> None:
    """A write the store refused is a 503 naming the failure, not a 200 that
    acknowledged a save which did not happen (the dashboard's own bar)."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    class _RefusingStore:
        def get(self, key: str, default: Any = None) -> Any:
            return default

        def __setitem__(self, key: str, value: Any) -> None:
            raise OSError("no writable backing store")

    monkeypatch.setattr(home_layouts, "_store", lambda: _RefusingStore())
    r = authed_client.put(f"/v1/workspaces/{ws}/home/layout", json={"regions": []})
    assert r.status_code == 503
    assert "was not saved" in r.json()["detail"]


def test_an_invalid_layout_payload_answers_422(admin_client, authed_client) -> None:
    """A note region naming a canonical resource breaks the reference contract;
    the route relays the service's refusal as 422."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    r = authed_client.put(
        f"/v1/workspaces/{ws}/home/layout",
        json={
            "regions": [
                {"id": "r-note", "kind": "note", "resource_type": "goal", "resource_id": "g1"}
            ]
        },
    )
    assert r.status_code == 422
    assert "note region" in r.json()["detail"]


def test_an_unknown_service_failure_is_not_swallowed_into_an_http_answer(
    admin_client, authed_client, monkeypatch
) -> None:
    """Only the failures with an answer of their own are translated; anything
    else propagates rather than being masked as a client error."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(home_layouts, "save_layout", _boom)
    with pytest.raises(RuntimeError, match="disk on fire"):
        authed_client.put(f"/v1/workspaces/{ws}/home/layout", json={"regions": []})


def test_a_pin_with_a_stale_revision_gets_409(admin_client, authed_client) -> None:
    """The pin route carries the same revision contract a full save does."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    saved = authed_client.put(
        f"/v1/workspaces/{ws}/home/layout",
        json={"regions": [{"id": "r-goals", "kind": "goals"}]},
    )
    assert saved.status_code == 200

    r = authed_client.post(
        f"/v1/workspaces/{ws}/home/regions/r-goals/pin",
        json={"pinned": True, "expectedRevision": 0},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["revision"] == 1


def test_pin_of_an_unknown_region_answers_422(admin_client, authed_client) -> None:
    """Pinning is not creation: a region the layout does not hold is refused."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    authed_client.put(
        f"/v1/workspaces/{ws}/home/layout", json={"regions": [{"id": "a", "kind": "goals"}]}
    )
    r = authed_client.post(f"/v1/workspaces/{ws}/home/regions/nope/pin", json={"pinned": True})
    assert r.status_code == 422
    assert "no region" in r.json()["detail"]


def test_projection_and_adaptive_reads_still_404_when_the_service_layer_refuses(
    admin_client, authed_client, monkeypatch
) -> None:
    """Defense in depth: the route checks membership itself, and answers 404
    again if the service beneath it refuses — the two layers agree."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    async def _invisible(user_id: str, workspace_id: str) -> None:
        raise home_projections.WorkspaceNotVisible(workspace_id)

    monkeypatch.setattr(home_projections, "list_projections", _invisible)
    monkeypatch.setattr(home_projections, "adaptive_items", _invisible)
    assert authed_client.get(f"/v1/workspaces/{ws}/home/projections").status_code == 404
    assert authed_client.get(f"/v1/workspaces/{ws}/home/adaptive").status_code == 404


def test_the_compose_route_answers_the_stored_layout_envelope(admin_client, authed_client) -> None:
    """The Agent's compose route success path: an unpinned region lands, and the
    answer is the full envelope (revision + regions) a client renders from."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    r = authed_client.post(
        f"/v1/workspaces/{ws}/home/adaptive/compose",
        json={
            "regions": [
                {"id": "agent-runs", "kind": "runs", "position": 5, "reason": "recent failures"}
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == 1
    assert "agent-runs" in {region["id"] for region in body["regions"]}


def test_the_compose_tool_refuses_malformed_payloads_without_a_compose() -> None:
    """A payload that is not a region list never reaches the layout service:
    the tool answers `composed: False` with the reason, and stores nothing.
    Without a Workspace context it refuses rather than guessing one."""
    from services.chat_completion import _tool_compose_home_adaptive

    orphaned = asyncio.run(
        _tool_compose_home_adaptive({"regions": [{"id": "r1", "kind": "goals"}]}, "user", None)
    )
    assert orphaned == {
        "composed": False,
        "error": "no Workspace context for this turn; Home is Workspace-scoped",
    }

    _set_tool_workspace("ws-tool-shape")
    try:
        not_a_list = asyncio.run(_tool_compose_home_adaptive({"regions": "nope"}, "user", None))
        assert not_a_list == {"composed": False, "error": "regions must be a list"}

        not_objects = asyncio.run(_tool_compose_home_adaptive({"regions": ["nope"]}, "user", None))
        assert not_objects["composed"] is False
        assert "region payload rejected" in not_objects["error"]
    finally:
        _set_tool_workspace(None)


def test_the_compose_tool_reports_the_layout_services_refusals(
    admin_client,
) -> None:
    """Pinned payloads, stale revisions and invalid compositions come back as
    the tool's `composed: False` carrying the service's own words — the Agent
    sees the same refusal the API route would have raised."""
    from services import home_layouts
    from services.chat_completion import _tool_compose_home_adaptive

    ws = _create_workspace(admin_client, name="Tool refusals WS")
    home_layouts.save_layout(ws, home_layouts.default_layout())
    assert home_layouts.load(ws).revision == 1

    _set_tool_workspace(ws)
    try:
        pinned = asyncio.run(
            _tool_compose_home_adaptive(
                {
                    "regions": [
                        {"id": "pinned-clone", "kind": "runs", "pinned": True, "position": 8}
                    ]
                },
                "user",
                None,
            )
        )
        assert pinned["composed"] is False
        assert "pinned" in pinned["error"]

        stale = asyncio.run(
            _tool_compose_home_adaptive(
                {
                    "regions": [{"id": "agent-1", "kind": "runs", "position": 9}],
                    "expected_revision": 0,
                },
                "user",
                None,
            )
        )
        assert stale["composed"] is False
        assert stale["revision"] == 1

        invalid_pair = asyncio.run(
            _tool_compose_home_adaptive(
                {
                    "regions": [
                        {
                            "id": "r-note",
                            "kind": "note",
                            "resource_type": "goal",
                            "resource_id": "g1",
                        }
                    ]
                },
                "user",
                None,
            )
        )
        assert invalid_pair["composed"] is False
        assert "not saved" in invalid_pair["error"]
    finally:
        _set_tool_workspace(None)

    # None of those refusals wrote anything: the layout is where it was.
    assert home_layouts.load(ws).revision == 1


def test_the_dismiss_tool_refuses_an_empty_identity_without_a_record() -> None:
    """An identity-less dismissal is refused with the service's own reason —
    the same ValueError the direct API caller would get."""
    from services import home_projections
    from services.chat_completion import _tool_dismiss_home_adaptive

    _set_tool_workspace("ws-dismiss-shape")
    try:
        refused = asyncio.run(
            _tool_dismiss_home_adaptive({"item_type": "goal", "item_id": ""}, "user", None)
        )
    finally:
        _set_tool_workspace(None)
    assert refused["dismissed"] is False
    assert "names the item type and id" in refused["error"]
    # Read back through the service's own view: no record exists for this
    # Workspace, so the refusal stored nothing. (A bare iteration over the
    # store is not an option: JsonStore has keys()/items(), not __iter__.)
    assert home_projections.dismissal_counts("ws-dismiss-shape") == {}


# ---------------------------------------------------------------------------
# Section reads: runs, chat, design, attention — each the canonical service's
# own answer, with the honest degraded states the issue asks for.
# ---------------------------------------------------------------------------


def test_the_runs_section_projects_only_this_workspaces_runs(
    admin_client, authed_client, monkeypatch
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    other = _create_workspace(admin_client, name="Other WS")

    summaries = [
        {"id": "run-other", "workspace_id": other, "dag_id": "dag-a", "status": "failed"},
        {"workspace_id": ws, "dag_id": "dag-b", "status": "running"},
        {"id": "run-mine", "workspace_id": ws, "dag_id": "dag-c", "status": "failed"},
    ]

    async def _runs(user_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        return summaries

    from services import dag_run_inspection

    monkeypatch.setattr(dag_run_inspection, "list_visible_runs", _runs)

    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    runs = next(s for s in body["sections"] if s["kind"] == "runs")
    assert runs["status"] == "ok"
    assert [i["resource_id"] for i in runs["items"]] == ["run-mine"]
    assert runs["items"][0]["href"] == "/dag-runs?run=run-mine"


def test_the_chat_section_titles_sessions_from_their_first_real_message(
    admin_client, authed_client
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    from models.schemas import ChatMessage, ChatSession

    now = datetime.now(UTC)
    stores.chat_sessions["sess-a"] = ChatSession(
        id="sess-a",
        user_id="user",
        title="Saved title",
        messages=[ChatMessage(id="m1", role="user", content="x" * 100)],
        created_at=now,
        updated_at=now,
    )
    stores.chat_sessions["sess-b"] = ChatSession(
        id="sess-b",
        user_id="user",
        title="Saved title",
        messages=[ChatMessage(id="m2", role="user", content="   ")],
        created_at=now,
        updated_at=now,
    )
    stores.chat_sessions["sess-c"] = ChatSession(
        id="sess-c",
        user_id="user",
        title="Empty but honest",
        messages=[],
        created_at=now,
        updated_at=now,
    )
    try:
        body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
        chat = next(s for s in body["sections"] if s["kind"] == "chat")
        assert chat["status"] == "ok"
        by_id = {i["resource_id"]: i for i in chat["items"]}
        assert by_id["sess-a"]["title"] == "x" * 80  # truncated to the title cap
        assert by_id["sess-b"]["title"] == "Saved title"  # whitespace is not a title
        assert by_id["sess-c"]["title"] == "Empty but honest"  # no messages at all
        assert by_id["sess-a"]["href"] == "/chat?session=sess-a"
    finally:
        for sid in ("sess-a", "sess-b", "sess-c"):
            stores.chat_sessions.pop(sid, None)


def test_the_design_section_reads_the_real_status_object(
    admin_client, authed_client, monkeypatch
) -> None:
    """The section answers from the status the design service actually publishes
    (`ready`, with its recorded cause) — a ready service is projectable, and an
    unready one says why instead of fabricating a miniature."""
    from services import design_service
    from services.design_service import DesignServiceStatus

    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    monkeypatch.setattr(
        design_service,
        "get_design_status",
        lambda: DesignServiceStatus(ready=False, cause="engine not initialized"),
    )
    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    design = next(s for s in body["sections"] if s["kind"] == "design")
    assert design["status"] == "unavailable"
    assert "engine not initialized" in design["reason"]

    monkeypatch.setattr(
        design_service, "get_design_status", lambda: DesignServiceStatus(ready=True)
    )
    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    design = next(s for s in body["sections"] if s["kind"] == "design")
    assert design["status"] == "ok"
    assert design["items"][0]["resource_id"] == "design-studio"
    assert design["items"][0]["href"] == "/design-studio"


def test_a_raising_design_status_reads_as_unavailable(
    admin_client, authed_client, monkeypatch
) -> None:
    def _boom() -> None:
        raise RuntimeError("status exploded")

    from services import design_service

    monkeypatch.setattr(design_service, "get_design_status", _boom)
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    design = next(s for s in body["sections"] if s["kind"] == "design")
    assert design["status"] == "unavailable"
    assert "RuntimeError" in design["reason"]


def test_the_attention_section_maps_entries_and_skips_unidentifiable_ones(
    admin_client, authed_client, monkeypatch
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    async def _attention(user_id: str, workspace_id: str, *, now: datetime) -> dict[str, Any]:
        return {
            "items": [
                {
                    "source_id": "att-1",
                    "reason": "goal blocked",
                    "answer_href": "/goals?goal=att-1",
                    "created_at": "t1",
                },
                {"reason": "no source id"},
                {"source_id": "att-2", "attention_class": "stale", "answer_href": None},
            ]
        }

    from services import attention as attention_service

    monkeypatch.setattr(attention_service, "list_attention", _attention)

    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    section = next(s for s in body["sections"] if s["kind"] == "attention")
    assert section["status"] == "ok"
    assert [i["resource_id"] for i in section["items"]] == ["att-1", "att-2"]
    assert section["items"][0]["title"] == "goal blocked"
    assert section["items"][0]["href"] == "/goals?goal=att-1"
    assert section["items"][1]["title"] == "stale"  # falls back to attention_class
    assert section["items"][1]["href"] == "/attention"  # default href


def test_attention_returning_none_reads_as_an_empty_section(
    admin_client, authed_client, monkeypatch
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    async def _none(user_id: str, workspace_id: str, *, now: datetime) -> None:
        return None

    from services import attention as attention_service

    monkeypatch.setattr(attention_service, "list_attention", _none)
    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    section = next(s for s in body["sections"] if s["kind"] == "attention")
    assert section["status"] == "empty"
    assert section["items"] == []


def test_projection_reads_refuse_a_non_member_at_the_service_layer(
    admin_client,
) -> None:
    """The service itself refuses before any section is computed — the route's
    404 is not the only guard, and the section readers never run for a
    stranger."""
    ws = _create_workspace(admin_client)
    with pytest.raises(home_projections.WorkspaceNotVisible):
        asyncio.run(home_projections.list_projections("user", ws))
    with pytest.raises(home_projections.WorkspaceNotVisible):
        asyncio.run(home_projections.adaptive_items("user", ws))


def test_adaptive_backlog_candidates_cover_blocked_critical_and_neutral(
    admin_client, authed_client
) -> None:
    """Blocked and highest-priority (wire `priority: 1`) items are candidates
    with evidence from their own state; a neutral item is nothing the Agent
    needs to surface now."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    blocked = authed_client.post(
        "/v1/backlog",
        json={
            "title": "Blocked deliverable",
            "workspace_id": ws,
            "status": "blocked",
            "source": "user request",
        },
    ).json()
    critical = authed_client.post(
        "/v1/backlog",
        json={
            "title": "Critical deliverable",
            "workspace_id": ws,
            "priority": 1,
            "source": "user request",
        },
    ).json()
    neutral = authed_client.post(
        "/v1/backlog",
        json={"title": "Ordinary deliverable", "workspace_id": ws, "source": "user request"},
    ).json()

    body = authed_client.get(f"/v1/workspaces/{ws}/home/adaptive").json()
    by_key = {c["key"]: c for c in body["candidates"]}
    assert by_key[f"backlog_item:{blocked['id']}"]["explain"].startswith("blocked")
    assert (
        by_key[f"backlog_item:{critical['id']}"]["explain"]
        == "critical-priority item in this Workspace's backlog"
    )
    assert f"backlog_item:{neutral['id']}" not in by_key


def test_adaptive_run_candidates_come_from_failed_runs_in_this_workspace(
    admin_client, authed_client, monkeypatch
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    summaries = [
        {"id": "run-failed", "workspace_id": ws, "dag_id": "dag-a", "status": "failed"},
        {"id": "run-ok", "workspace_id": ws, "dag_id": "dag-b", "status": "succeeded"},
        {"id": "run-foreign", "workspace_id": "ws-other", "dag_id": "dag-c", "status": "failed"},
        {"workspace_id": ws, "dag_id": "dag-d", "status": "failed"},
    ]

    async def _runs(user_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        return summaries

    from services import dag_run_inspection

    monkeypatch.setattr(dag_run_inspection, "list_visible_runs", _runs)

    body = authed_client.get(f"/v1/workspaces/{ws}/home/adaptive").json()
    assert [c["key"] for c in body["candidates"]] == ["run:run-failed"]
    candidate = body["candidates"][0]
    assert candidate["explain"] == "this run failed; open it to see what failed"
    assert candidate["href"] == "/dag-runs?run=run-failed"


def test_a_failing_backlog_service_degrades_the_sections_it_feeds(
    admin_client, authed_client, monkeypatch
) -> None:
    """The canonical read failing is that section's `unavailable`, and no
    adaptive candidates claim its evidence — Home still answers for the rest."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")

    from services import backlog as backlog_service

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("backlog down")

    monkeypatch.setattr(backlog_service, "list_items", _boom)

    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    backlog = next(s for s in body["sections"] if s["kind"] == "backlog")
    assert backlog["status"] == "unavailable"
    assert "RuntimeError" in backlog["reason"]

    adaptive = authed_client.get(f"/v1/workspaces/{ws}/home/adaptive").json()
    assert all(c["item_type"] != "backlog_item" for c in adaptive["candidates"])


def test_a_failing_runs_service_degrades_runs_without_touching_backlog(
    admin_client, authed_client, monkeypatch
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

    from services import dag_run_inspection

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("runs down")

    monkeypatch.setattr(dag_run_inspection, "list_visible_runs", _boom)

    body = authed_client.get(f"/v1/workspaces/{ws}/home/projections").json()
    runs = next(s for s in body["sections"] if s["kind"] == "runs")
    assert runs["status"] == "unavailable"

    adaptive = authed_client.get(f"/v1/workspaces/{ws}/home/adaptive").json()
    assert f"backlog_item:{item['id']}" in [c["key"] for c in adaptive["candidates"]]
    assert all(c["item_type"] != "run" for c in adaptive["candidates"])
