"""Workspace BacklogItem work-source API (#98): member writes, outsider 404s.

The routes are the production root the reachability disposition named for the
``maistro.backlog`` package: an authenticated Workspace member edits the one
canonical store through them, a stale edit gets an explicit 409 carrying the
current version, and anything outside the caller's Workspace is answered with
the same 404 an unknown item gets.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.backlog.store import InMemoryBacklogStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal


def _as_user(app: FastAPI, user_id: str) -> None:
    principal = AuthenticatedPrincipal(
        user_id=user_id, token=f"token-{user_id}", roles=frozenset({"user"})
    )
    app.dependency_overrides[verify_api_key] = lambda: principal


class _Api(SimpleNamespace):
    app: FastAPI
    client: TestClient
    workspaces: InMemoryWorkspaceStore
    store: InMemoryBacklogStore


@pytest.fixture
async def api() -> AsyncIterator[_Api]:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    store = InMemoryBacklogStore()
    app = FastAPI()
    app.state.container = SimpleNamespace(
        project_scope_store=projects,
        backlog_store=store,
    )
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(workspaces)
    client = TestClient(app)
    try:
        yield _Api(app=app, client=client, workspaces=workspaces, store=store)
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


@pytest.fixture
async def bare_app() -> AsyncIterator[tuple[TestClient, str]]:
    """The 503 harness: a Workspace store, but no Container-level backlog store."""
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    workspace = await workspaces.create(creator_user_id="owner", name="Alpha")
    app = FastAPI()
    app.include_router(workspace_api.router)
    workspace_api.configure_workspace_store(workspaces)
    client = TestClient(app)
    try:
        yield client, workspace.workspace_id
    finally:
        client.close()
        workspace_api.configure_workspace_store(None)


async def _workspace(api: _Api) -> str:
    workspace = await api.workspaces.create(creator_user_id="owner", name="Alpha")
    await api.workspaces.set_membership(
        workspace.workspace_id, user_id="member", role=WorkspaceRole.MEMBER
    )
    return workspace.workspace_id


def _items_path(workspace_id: str, suffix: str = "") -> str:
    return f"/workspaces/{workspace_id}/backlog-items{suffix}"


async def test_member_creates_reads_and_lists_items(api: _Api) -> None:
    workspace_id = await _workspace(api)
    _as_user(api.app, "member")

    created = api.client.post(
        _items_path(workspace_id),
        json={"title": "Wire the work-source", "tags": ["infra"], "milestone": "M3"},
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["workspace_id"] == workspace_id
    assert item["title"] == "Wire the work-source"
    assert item["status"] == "open"
    assert item["version"] == 1
    assert item["tags"] == ["infra"]
    assert item["milestone"] == "M3"

    fetched = api.client.get(_items_path(workspace_id, f"/{item['item_id']}"))
    assert fetched.status_code == 200
    assert fetched.json()["item_id"] == item["item_id"]

    listing = api.client.get(_items_path(workspace_id))
    assert [row["item_id"] for row in listing.json()] == [item["item_id"]]

    by_tag = api.client.get(_items_path(workspace_id), params={"tag": "other"})
    assert by_tag.json() == []
    by_status = api.client.get(_items_path(workspace_id), params={"status": "in_progress"})
    assert by_status.json() == []
    roots = api.client.get(_items_path(workspace_id), params={"roots_only": "true"})
    assert [row["item_id"] for row in roots.json()] == [item["item_id"]]


async def test_create_with_unknown_parent_answers_404(api: _Api) -> None:
    workspace_id = await _workspace(api)
    _as_user(api.app, "member")

    response = api.client.post(
        _items_path(workspace_id),
        json={"title": "Child", "parent_id": "no-such-item"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "BacklogItem not found"


async def test_outsider_and_foreign_workspace_get_the_same_404(api: _Api) -> None:
    workspace_id = await _workspace(api)
    _as_user(api.app, "member")
    item_id = api.client.post(_items_path(workspace_id), json={"title": "Secret work"}).json()[
        "item_id"
    ]

    other = await api.workspaces.create(creator_user_id="owner", name="Beta")
    await api.workspaces.set_membership(
        other.workspace_id, user_id="member", role=WorkspaceRole.MEMBER
    )
    # A member of BOTH Workspaces asking under Beta for Alpha's item id — or
    # for an id that exists nowhere — gets the same answer both times, so the
    # store is not an existence oracle for foreign work.
    foreign = api.client.get(_items_path(other.workspace_id, f"/{item_id}"))
    unknown = api.client.get(_items_path(other.workspace_id, "/no-such-item"))
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json()["detail"] == unknown.json()["detail"] == "BacklogItem not found"

    # A full outsider (no membership anywhere) is stopped at the Workspace
    # boundary with a 404 that does not disclose the Workspace either.
    _as_user(api.app, "outsider")
    assert api.client.get(_items_path(workspace_id, f"/{item_id}")).status_code == 404
    assert api.client.get(_items_path(other.workspace_id)).status_code == 404


async def test_patch_bumps_version_and_stale_edit_gets_409(api: _Api) -> None:
    workspace_id = await _workspace(api)
    _as_user(api.app, "member")
    item_id = api.client.post(
        _items_path(workspace_id), json={"title": "Original", "milestone": "M3"}
    ).json()["item_id"]

    edited = api.client.patch(
        _items_path(workspace_id, f"/{item_id}"),
        json={"expected_version": 1, "title": "Renamed", "milestone": None},
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["title"] == "Renamed"
    assert body["version"] == 2
    # An explicit null clears a clearable field.
    assert body["milestone"] is None

    stale = api.client.patch(
        _items_path(workspace_id, f"/{item_id}"),
        json={"expected_version": 1, "details": "stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_version"] == 2

    # A field absent from the body means "no opinion", not "clear": the
    # tri-state mapping via model_fields_set.
    no_opinion = api.client.patch(
        _items_path(workspace_id, f"/{item_id}"),
        json={"expected_version": 2, "details": "now with detail"},
    )
    assert no_opinion.status_code == 200
    assert no_opinion.json()["details"] == "now with detail"


async def test_status_edit_moves_between_mutable_statuses(api: _Api) -> None:
    workspace_id = await _workspace(api)
    _as_user(api.app, "member")
    item_id = api.client.post(_items_path(workspace_id), json={"title": "Track me"}).json()[
        "item_id"
    ]

    moved = api.client.patch(
        _items_path(workspace_id, f"/{item_id}"),
        json={"expected_version": 1, "status": "in_progress"},
    )
    assert moved.status_code == 200
    assert moved.json()["status"] == "in_progress"

    # Terminal statuses are closed evidence, not an ordinary edit: the store
    # refuses the transition and the route answers 422, not a leaked 500.
    refused = api.client.patch(
        _items_path(workspace_id, f"/{item_id}"),
        json={"expected_version": 2, "status": "done"},
    )
    assert refused.status_code == 422
    assert "close_item" in refused.json()["detail"]


async def test_close_requires_evidence_and_reopen_leaves_it(api: _Api) -> None:
    workspace_id = await _workspace(api)
    _as_user(api.app, "member")
    item_id = api.client.post(_items_path(workspace_id), json={"title": "Finish me"}).json()[
        "item_id"
    ]

    bad_outcome = api.client.post(
        _items_path(workspace_id, f"/{item_id}/close"),
        json={
            "expected_version": 1,
            "outcome": "open",
            "closure_summary": "not terminal",
            "evidence_refs": ["run:abc"],
        },
    )
    assert bad_outcome.status_code == 422

    closed = api.client.post(
        _items_path(workspace_id, f"/{item_id}/close"),
        json={
            "expected_version": 1,
            "outcome": "done",
            "closure_summary": "conformance suite green",
            "evidence_refs": ["run:abc", "spec:SPEC-1"],
        },
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "done"
    assert body["version"] == 2
    assert body["closure"]["summary"] == "conformance suite green"
    assert body["closure"]["evidence_refs"] == ["run:abc", "spec:SPEC-1"]

    stale_close = api.client.post(
        _items_path(workspace_id, f"/{item_id}/close"),
        json={
            "expected_version": 1,
            "outcome": "done",
            "closure_summary": "stale",
            "evidence_refs": ["run:abc"],
        },
    )
    assert stale_close.status_code == 409

    reopened = api.client.post(
        _items_path(workspace_id, f"/{item_id}/reopen"),
        json={"expected_version": 2},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"
    assert reopened.json()["closure"] is None
    assert reopened.json()["version"] == 3

    # Reopening a live item is refused with evidence-shaped 422, and a stale
    # reopen is a 409 like every other content mutation.
    reopen_live = api.client.post(
        _items_path(workspace_id, f"/{item_id}/reopen"),
        json={"expected_version": 3},
    )
    assert reopen_live.status_code == 422
    stale_reopen = api.client.post(
        _items_path(workspace_id, f"/{item_id}/reopen"),
        json={"expected_version": 1},
    )
    assert stale_reopen.status_code == 409
    assert stale_reopen.json()["detail"]["current_version"] == 3


async def test_claim_lease_is_exclusive_and_releasable(api: _Api) -> None:
    workspace_id = await _workspace(api)
    _as_user(api.app, "member")
    item_id = api.client.post(
        _items_path(workspace_id), json={"title": "One worker at a time"}
    ).json()["item_id"]

    # No body at all: the default lease applies.
    claimed = api.client.post(_items_path(workspace_id, f"/{item_id}/claim"))
    assert claimed.status_code == 200, claimed.text
    claim = claimed.json()
    assert claim["claimed_by"] == "member"
    assert claim["released_at"] is None

    second = api.client.post(
        _items_path(workspace_id, f"/{item_id}/claim"), json={"lease_seconds": 60}
    )
    assert second.status_code == 409
    assert second.json()["detail"]["claim_id"] == claim["claim_id"]

    extended = api.client.post(
        _items_path(workspace_id, f"/{item_id}/claims/extend"),
        json={"claim_id": claim["claim_id"], "lease_seconds": 1800},
    )
    assert extended.status_code == 200
    # The lease is reset from now to now + lease_seconds, so a longer lease
    # moves the expiry later and the claim id is unchanged.
    assert extended.json()["lease_expires_at"] > claim["lease_expires_at"]
    assert extended.json()["claim_id"] == claim["claim_id"]

    extend_unknown = api.client.post(
        _items_path(workspace_id, f"/{item_id}/claims/extend"),
        json={"claim_id": "no-such-claim", "lease_seconds": 60},
    )
    assert extend_unknown.status_code == 409

    released = api.client.post(
        _items_path(workspace_id, f"/{item_id}/claims/release"),
        json={"claim_id": claim["claim_id"]},
    )
    assert released.status_code == 204

    reclaim = api.client.post(
        _items_path(workspace_id, f"/{item_id}/claim"), json={"lease_seconds": 60}
    )
    assert reclaim.status_code == 200

    # A claim never mutated the item itself: same version, and the event log
    # distinguishes claim events from content edits.
    item = api.client.get(_items_path(workspace_id, f"/{item_id}")).json()
    assert item["version"] == 1


async def test_events_record_provenance_in_order(api: _Api) -> None:
    workspace_id = await _workspace(api)
    _as_user(api.app, "member")
    item_id = api.client.post(_items_path(workspace_id), json={"title": "Audited"}).json()[
        "item_id"
    ]
    api.client.patch(
        _items_path(workspace_id, f"/{item_id}"),
        json={"expected_version": 1, "title": "Audited v2"},
    )

    events = api.client.get(_items_path(workspace_id, f"/{item_id}/events"))
    assert events.status_code == 200
    kinds = [event["kind"] for event in events.json()]
    assert kinds == ["created", "updated"]
    assert [event["item_version"] for event in events.json()] == [1, 2]
    assert {event["actor"] for event in events.json()} == {"member"}


async def test_missing_store_is_503(bare_app: tuple[TestClient, str]) -> None:
    client, workspace_id = bare_app
    _as_user(client.app, "owner")
    response = client.get(_items_path(workspace_id))
    assert response.status_code == 503
    assert "work-source store" in response.json()["detail"]
