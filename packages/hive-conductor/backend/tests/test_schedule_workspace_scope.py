"""Schedule CRUD and manual fire are scoped to the caller's Workspaces (#1201).

Two non-admin principals, each holding only the coarse ``schedules.write``
capability and each owning one canonical Workspace. The global capability is
what lets them reach ``/v1/schedules`` at all; which rows they can see or act
on is decided by canonical Workspace membership, not by a ``user_id`` string.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("integration")]

_BODY = {"name": "nightly", "cron_expression": "0 9 * * *", "mission_template_id": "tpl"}


def _workspace(owner: str, name: str) -> Any:
    from services.workspace_authority import create_workspace

    return asyncio.run(
        create_workspace(
            creator_user_id=owner,
            name=name,
            persona_template_id="default",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )
    )


def _root_project(workspace_id: str) -> str:
    from services import workspace_authority

    async def _root() -> str:
        store = await workspace_authority.canonical_workspace_store()
        root = await store.project_store.root_for_workspace(workspace_id)
        return root.project_id

    return asyncio.run(_root())


@pytest.fixture
def principals() -> Iterator[dict[str, Any]]:
    """alice and bob: schedules.write, elevated, each with one Workspace."""
    import stores
    from fastapi.testclient import TestClient
    from main import app

    clients: dict[str, Any] = {}
    for username in ("alice", "bob"):
        stores.users[username] = stores.users["user"].model_copy(
            update={"id": username, "username": username, "permissions": ["schedules.write"]}
        )
        client = TestClient(app)
        login = client.post("/v1/auth/login", json={"username": username, "password": "testpass"})
        assert login.status_code == 200, login.text
        elevated = client.post(
            "/v1/auth/elevate",
            json={
                "password": "testpass",
                "permissions": ["schedules.write"],
                "task_id": "schedule-scope-test",
            },
        )
        assert elevated.status_code == 200, elevated.text
        clients[username] = client
    created: list[str] = []
    try:
        yield {
            "alice": clients["alice"],
            "bob": clients["bob"],
            "alice_ws": _workspace("alice", "Alice schedules"),
            "bob_ws": _workspace("bob", "Bob schedules"),
            "created": created,
        }
    finally:
        for sid in created:
            stores.schedules.pop(sid, None)
        for username in ("alice", "bob"):
            stores.users.pop(username, None)


def _create(principals: dict[str, Any], who: str, **extra: Any) -> dict[str, Any]:
    response = principals[who].post(
        "/v1/schedules",
        json={**_BODY, "workspace_id": principals[f"{who}_ws"].id, **extra},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    principals["created"].append(body["id"])
    return body


def test_create_binds_owner_and_scope_from_the_session(principals: dict[str, Any]) -> None:
    workspace_id = principals["alice_ws"].id
    body = _create(principals, "alice", user_id="mallory")

    assert body["user_id"] == "alice", "a client user_id is not authority"
    assert body["workspace_id"] == workspace_id
    assert body["project_id"] == _root_project(workspace_id)


@pytest.mark.parametrize("selection", [None, "", "bob"])
def test_create_without_an_authorized_workspace_is_refused(
    principals: dict[str, Any], selection: str | None
) -> None:
    import stores

    before = set(stores.schedules.keys())
    body: dict[str, Any] = dict(_BODY)
    if selection == "bob":
        body["workspace_id"] = principals["bob_ws"].id
    elif selection is not None:
        body["workspace_id"] = selection

    response = principals["alice"].post("/v1/schedules", json=body)

    assert response.status_code == 403, response.text
    assert set(stores.schedules.keys()) == before


def test_create_refuses_a_project_outside_the_selected_workspace(
    principals: dict[str, Any],
) -> None:
    response = principals["alice"].post(
        "/v1/schedules",
        json={
            **_BODY,
            "workspace_id": principals["alice_ws"].id,
            "project_id": _root_project(principals["bob_ws"].id),
        },
    )
    assert response.status_code == 403, response.text


def test_list_shows_only_the_callers_workspaces(principals: dict[str, Any]) -> None:
    import stores

    mine = _create(principals, "alice")
    theirs = _create(principals, "bob")
    # The seeded demo row and any pre-#1201 row name no Workspace.
    assert any(not getattr(row, "workspace_id", "") for row in stores.schedules.values())

    alice_ids = {row["id"] for row in principals["alice"].get("/v1/schedules").json()}
    bob_ids = {row["id"] for row in principals["bob"].get("/v1/schedules").json()}

    assert alice_ids == {mine["id"]}
    assert bob_ids == {theirs["id"]}


def test_foreign_schedules_are_indistinguishable_from_missing(
    principals: dict[str, Any],
) -> None:
    import stores

    theirs = _create(principals, "bob")
    sid = theirs["id"]
    before = stores.schedules[sid].model_dump()
    alice = principals["alice"]

    responses = [
        alice.get(f"/v1/schedules/{sid}"),
        alice.put(f"/v1/schedules/{sid}", json={"name": "hijacked", "enabled": False}),
        alice.post(f"/v1/schedules/{sid}/run"),
        alice.delete(f"/v1/schedules/{sid}"),
    ]
    missing = alice.get("/v1/schedules/does-not-exist")

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json() == missing.json() == {"detail": "schedule not found"}
    assert stores.schedules[sid].model_dump() == before, "the foreign row is unchanged"
    assert stores.schedules[sid].last_run_id is None, "no Run admitted for the foreign row"


def test_ownerless_legacy_rows_are_visible_to_nobody(principals: dict[str, Any]) -> None:
    assert principals["alice"].get("/v1/schedules/sch-1").status_code == 404
    assert principals["alice"].post("/v1/schedules/sch-1/run").status_code == 404


def test_owner_can_read_update_and_delete_in_scope(principals: dict[str, Any]) -> None:
    import stores

    sid = _create(principals, "alice")["id"]
    alice = principals["alice"]

    assert alice.get(f"/v1/schedules/{sid}").status_code == 200
    renamed = alice.put(f"/v1/schedules/{sid}", json={"name": "renamed"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "renamed"
    assert alice.delete(f"/v1/schedules/{sid}").status_code == 204
    assert sid not in stores.schedules


def test_update_cannot_transfer_owner_or_scope(principals: dict[str, Any]) -> None:
    alice_ws = principals["alice_ws"].id
    sid = _create(principals, "alice")["id"]

    updated = principals["alice"].put(
        f"/v1/schedules/{sid}",
        json={
            "user_id": "bob",
            "workspace_id": principals["bob_ws"].id,
            "project_id": _root_project(principals["bob_ws"].id),
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["user_id"] == "alice"
    assert updated.json()["workspace_id"] == alice_ws
    assert updated.json()["project_id"] == _root_project(alice_ws)
    assert principals["bob"].get(f"/v1/schedules/{sid}").status_code == 404


def test_membership_removal_revokes_access(principals: dict[str, Any]) -> None:
    from services import workspace_authority

    sid = _create(principals, "alice")["id"]
    workspace_id = principals["alice_ws"].id
    asyncio.run(workspace_authority.set_member(workspace_id, user_id="bob", role="editor"))
    assert principals["bob"].get(f"/v1/schedules/{sid}").status_code == 200

    asyncio.run(workspace_authority.remove_member(workspace_id, user_id="bob"))

    assert principals["bob"].get(f"/v1/schedules/{sid}").status_code == 404
    assert sid not in {row["id"] for row in principals["bob"].get("/v1/schedules").json()}
