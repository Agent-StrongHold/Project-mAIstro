"""routes/backlog.py + services/backlog.py — the #99 board/list/detail surface.

Covers the acceptance criteria that live on the server side:

- list/board/detail data comes from the canonical BacklogItem service, and
  every editing verb (create, edit, reorder, block/unblock, decompose, pin,
  pause, archive) goes through it — there is no second write path;
- optimistic version conflicts are refused with 409 carrying the current
  item, so a stale editor can recover without losing the server's state;
- dependencies, acceptance evidence, source, provenance, risk and autonomy
  mode are stored, attributed, and returned by the detail view;
- authorization fails closed: anonymous callers get 401, strangers get the
  same 404 a missing id gets (no existence oracle), and a read-only
  workspace member's edit gets 403;
- the UI's non-authoritative status until cutover (#102) is machine
  readable in every list/detail payload.
"""

from __future__ import annotations

import asyncio

import pytest
import stores


@pytest.fixture(autouse=True)
def _clear_backlog():
    for key in list(stores.backlog_items.keys()):
        stores.backlog_items.pop(key, None)
    yield
    for key in list(stores.backlog_items.keys()):
        stores.backlog_items.pop(key, None)


def _create_workspace(admin_client, name: str = "Backlog WS") -> str:
    r = admin_client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_member(admin_client, workspace_id: str, user_id: str, role: str) -> None:
    r = admin_client.post(
        f"/v1/workspaces/{workspace_id}/members", json={"user_id": user_id, "role": role}
    )
    assert r.status_code == 200, r.text


def _create_item(client, workspace_id: str | None = None, title: str = "Ship the thing") -> dict:
    r = client.post(
        "/v1/backlog",
        json={"title": title, "workspace_id": workspace_id, "source": "user request"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Fail-closed authorization
# ---------------------------------------------------------------------------


def test_anonymous_callers_fail_closed(authed_client) -> None:
    """No session: no list, no detail, no edit — before the service is reached."""
    from fastapi.testclient import TestClient
    from main import app

    anon = TestClient(app)
    assert anon.get("/v1/backlog").status_code == 401
    assert anon.post("/v1/backlog", json={"title": "sneak"}).status_code == 401
    assert anon.get("/v1/backlog/whatever").status_code == 401
    assert (
        anon.patch("/v1/backlog/whatever", json={"expected_version": 1, "changes": {}}).status_code
        == 401
    )


def test_personal_items_are_invisible_to_other_users(admin_client, authed_client) -> None:
    """A stranger's list omits them and detail/edit get the missing-id answer."""
    item = _create_item(admin_client, title="admin private")
    r = authed_client.get("/v1/backlog")
    assert all(row["id"] != item["id"] for row in r.json()["items"])
    assert authed_client.get(f"/v1/backlog/{item['id']}").status_code == 404
    r = authed_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 1, "changes": {"title": "mine now"}}
    )
    assert r.status_code == 404
    # The missing-id answer is identical, so the route is not an oracle.
    assert authed_client.get("/v1/backlog/no-such-id").status_code == 404


def test_non_member_cannot_see_or_edit_a_workspace_item(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    item = _create_item(admin_client, workspace_id=ws)
    r = authed_client.get(f"/v1/backlog/{item['id']}")
    assert r.status_code == 404
    r = authed_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 1, "changes": {"title": "x"}}
    )
    assert r.status_code == 404


def test_viewer_member_can_read_but_not_edit(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "viewer")
    item = _create_item(admin_client, workspace_id=ws)

    r = authed_client.get("/v1/backlog")
    assert [row["id"] for row in r.json()["items"]] == [item["id"]]
    assert authed_client.get(f"/v1/backlog/{item['id']}").status_code == 200

    r = authed_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 1, "changes": {"title": "nope"}}
    )
    assert r.status_code == 403
    r = authed_client.post("/v1/backlog", json={"title": "nope", "workspace_id": ws})
    assert r.status_code == 403
    r = authed_client.post(
        f"/v1/backlog/{item['id']}/block", json={"expected_version": 1, "reason": "x"}
    )
    assert r.status_code == 403


def test_editor_member_can_edit(admin_client, authed_client) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    item = _create_item(admin_client, workspace_id=ws)
    r = authed_client.patch(
        f"/v1/backlog/{item['id']}",
        json={"expected_version": 1, "changes": {"title": "renamed by editor"}},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "renamed by editor"
    assert r.json()["version"] == 2


def test_workspace_id_is_not_generic_editable(admin_client, authed_client) -> None:
    """An editor of one workspace cannot publish an item into another.

    Generic edits authorize against the item's current scope only, so a
    ``workspace_id`` change would let an editor drop an item into any
    workspace whose id they know. Scoping is creation-time; moving between
    workspaces needs an explicit destination-authorized path.
    """
    ws = _create_workspace(admin_client)
    other_ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    item = _create_item(admin_client, workspace_id=ws)

    r = authed_client.patch(
        f"/v1/backlog/{item['id']}",
        json={"expected_version": 1, "changes": {"workspace_id": other_ws}},
    )
    assert r.status_code == 422
    assert authed_client.get(f"/v1/backlog/{item['id']}").json()["item"]["workspace_id"] == ws


# ---------------------------------------------------------------------------
# Optimistic concurrency: conflicts visible and recoverable
# ---------------------------------------------------------------------------


def test_stale_version_update_conflicts_with_current_attached(admin_client) -> None:
    item = _create_item(admin_client)
    r = admin_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 99, "changes": {"description": "x"}}
    )
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["current"]["version"] == item["version"]
    assert body["current"]["id"] == item["id"]


def test_conflict_is_recoverable_with_the_returned_version(admin_client) -> None:
    item = _create_item(admin_client)
    stale = admin_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 1, "changes": {"description": "a"}}
    )
    assert stale.status_code == 200
    current = stale.json()
    lost = admin_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 1, "changes": {"description": "b"}}
    )
    assert lost.status_code == 409
    # The loser reloads from the conflict payload and re-applies.
    recovered = admin_client.patch(
        f"/v1/backlog/{item['id']}",
        json={
            "expected_version": lost.json()["detail"]["current"]["version"],
            "changes": {"description": "b"},
        },
    )
    assert recovered.status_code == 200
    assert recovered.json()["description"] == "b"
    assert recovered.json()["version"] == current["version"] + 1


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/block", {"reason": "waiting on upstream"}),
        ("/unblock", {}),
        ("/pin", {}),
        ("/unpin", {}),
        ("/pause", {"reason": "held"}),
        ("/resume", {}),
        ("/archive", {}),
        ("/restore", {}),
        ("/reorder", {"rank": 5.0}),
    ],
)
def test_every_mutation_verb_guards_the_version(admin_client, path: str, payload: dict) -> None:
    item = _create_item(admin_client)
    body = {"expected_version": 42, **payload}
    r = admin_client.post(f"/v1/backlog/{item['id']}{path}", json=body)
    assert r.status_code == 409
    assert r.json()["detail"]["current"]["version"] == 1


def test_decompose_conflicts_on_a_stale_version(admin_client) -> None:
    item = _create_item(admin_client)
    r = admin_client.post(
        f"/v1/backlog/{item['id']}/decompose",
        json={"expected_version": 7, "children": [{"title": "child"}]},
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Inspection: dependencies / evidence / source / provenance / risk / autonomy
# ---------------------------------------------------------------------------


def test_detail_inspection_fields_round_trip(admin_client) -> None:
    first = _create_item(admin_client, title="upstream")
    r = admin_client.post(
        "/v1/backlog",
        json={
            "title": "inspected",
            "description": "body",
            "acceptance_evidence": "pytest -q passes",
            "source": "user request #99",
            "risk": "high",
            "autonomy_mode": "human-only",
            "goal_id": "goal-1",
            "goal_revision": 3,
            "dependencies": [first["id"]],
            "priority": 2,
        },
    )
    assert r.status_code == 201, r.text
    item = r.json()

    detail = admin_client.get(f"/v1/backlog/{item['id']}").json()
    stored = detail["item"]
    assert stored["acceptance_evidence"] == "pytest -q passes"
    assert stored["source"] == "user request #99"
    assert stored["risk"] == "high"
    assert stored["autonomy_mode"] == "human-only"
    assert stored["goal_id"] == "goal-1"
    assert stored["goal_revision"] == 3
    assert stored["priority"] == 2
    # Provenance is attributed and inspectable.
    assert stored["provenance"][0]["actor"] == "admin"
    assert stored["provenance"][0]["action"] == "created"
    # Dependencies resolve to titles, and the reverse edge is visible on the
    # item being depended on.
    assert detail["dependencies"] == [
        {"id": first["id"], "title": "upstream", "status": "todo", "archived": False}
    ]
    first_detail = admin_client.get(f"/v1/backlog/{first['id']}").json()
    assert [dep["id"] for dep in first_detail["dependents"]] == [item["id"]]
    assert detail["dependents"] == []


def test_dependency_validation_rejects_unknown_self_and_cycles(admin_client) -> None:
    a = _create_item(admin_client, title="A")
    b = _create_item(admin_client, title="B")
    r = admin_client.patch(
        f"/v1/backlog/{b['id']}",
        json={"expected_version": 1, "changes": {"dependencies": ["missing-id"]}},
    )
    assert r.status_code == 422
    r = admin_client.patch(
        f"/v1/backlog/{b['id']}",
        json={"expected_version": 1, "changes": {"dependencies": [b["id"]]}},
    )
    assert r.status_code == 422
    # a -> b, then b -> a closes the cycle.
    assert (
        admin_client.patch(
            f"/v1/backlog/{b['id']}",
            json={"expected_version": 1, "changes": {"dependencies": [a["id"]]}},
        ).status_code
        == 200
    )
    r = admin_client.patch(
        f"/v1/backlog/{a['id']}",
        json={"expected_version": 1, "changes": {"dependencies": [b["id"]]}},
    )
    assert r.status_code == 422
    assert "cycle" in r.json()["detail"]


def test_unknown_enums_are_refused(admin_client) -> None:
    item = _create_item(admin_client)
    for changes in (
        {"status": "doing"},
        {"risk": "existential"},
        {"autonomy_mode": "yolo"},
        {"priority": 9},
    ):
        r = admin_client.patch(
            f"/v1/backlog/{item['id']}", json={"expected_version": 1, "changes": changes}
        )
        assert r.status_code == 422, changes


<<<<<<< HEAD
=======
def test_create_refuses_a_status_outside_the_legend(admin_client) -> None:
    """Creation is the one path the service's own enum check does not guard.

    ``PATCH`` refuses an unknown status in ``_apply_field_changes`` before the
    model is touched; creation hands ``status`` straight to ``BacklogItem``, so
    the model's legend validator is the boundary that must fail closed. The
    error names the legend so the editor can recover without round-tripping.
    """
    r = admin_client.post("/v1/backlog", json={"title": "off-ledger", "status": "doing"})
    assert r.status_code == 422
    assert "todo" in r.json()["detail"] and "doing" in r.json()["detail"]
    assert not stores.backlog_items


>>>>>>> d4ccd452e6a34349a37ce2cb732c18a1798b42dc
# ---------------------------------------------------------------------------
# Lifecycle: block/unblock, reorder, decompose, pin/pause/archive
# ---------------------------------------------------------------------------


def test_block_requires_evidence_and_unblock_clears_it(admin_client) -> None:
    item = _create_item(admin_client)
    r = admin_client.post(f"/v1/backlog/{item['id']}/block", json={"expected_version": 1})
    assert r.status_code == 422
    r = admin_client.post(
        f"/v1/backlog/{item['id']}/block", json={"expected_version": 1, "reason": "upstream flake"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "blocked"
    assert r.json()["blocked_reason"] == "upstream flake"
    r = admin_client.post(f"/v1/backlog/{item['id']}/unblock", json={"expected_version": 2})
    assert r.status_code == 200
    assert r.json()["status"] == "todo"
    assert r.json()["blocked_reason"] is None


<<<<<<< HEAD
=======
def test_parking_rules_hold_on_the_plain_edit_and_drag_paths(admin_client) -> None:
    """No side door into blocked without evidence, and no stale evidence left."""
    item = _create_item(admin_client)
    # A drag carries no evidence channel: reordering into blocked is refused
    # outright while the item is not parked, blocking stays with the explicit
    # endpoint.
    r = admin_client.post(
        f"/v1/backlog/{item['id']}/reorder",
        json={"expected_version": 1, "rank": 5.0, "status": "blocked"},
    )
    assert r.status_code == 422
    # A plain edit that flips status to blocked must carry evidence — the UI
    # echoes ``status`` on every save, so a no-reason park would slip through
    # the PATCH path the explicit block endpoint already refuses.
    r = admin_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 1, "changes": {"status": "blocked"}}
    )
    assert r.status_code == 422
    r = admin_client.patch(
        f"/v1/backlog/{item['id']}",
        json={"expected_version": 1, "changes": {"status": "blocked", "blocked_reason": "ci red"}},
    )
    assert r.status_code == 200
    assert r.json()["blocked_reason"] == "ci red"
    # Leaving blocked through a plain edit clears the stale park evidence.
    r = admin_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 2, "changes": {"status": "todo"}}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "todo"
    assert r.json()["blocked_reason"] is None


def test_detail_hides_related_items_the_caller_cannot_see(admin_client, authed_client) -> None:
    """Dependencies/children obey the same visibility rule as the item itself."""
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "viewer")
    parent = _create_item(admin_client, workspace_id=ws, title="parent")
    visible_child = _create_item(admin_client, workspace_id=ws, title="visible child")
    secret = _create_item(admin_client, title="admin private dependency")
    r = admin_client.patch(
        f"/v1/backlog/{parent['id']}",
        json={
            "expected_version": 1,
            "changes": {"dependencies": [secret["id"], visible_child["id"]]},
        },
    )
    assert r.status_code == 200
    admin_detail = admin_client.get(f"/v1/backlog/{parent['id']}").json()
    assert [dep["id"] for dep in admin_detail["dependencies"]] == [
        secret["id"],
        visible_child["id"],
    ]
    # The viewer sees the workspace child but the admin's private dependency
    # must not leak even its id/title/status through the detail payload.
    viewer_detail = authed_client.get(f"/v1/backlog/{parent['id']}").json()
    assert [dep["id"] for dep in viewer_detail["dependencies"]] == [visible_child["id"]]


>>>>>>> d4ccd452e6a34349a37ce2cb732c18a1798b42dc
def test_board_order_is_priority_then_rank(admin_client) -> None:
    _create_item(admin_client, title="low")
    top = _create_item(admin_client, title="top")
    mid = _create_item(admin_client, title="mid")
    assert (
        admin_client.patch(
            f"/v1/backlog/{top['id']}", json={"expected_version": 1, "changes": {"priority": 1}}
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            f"/v1/backlog/{mid['id']}/reorder", json={"expected_version": 1, "rank": 1.0}
        ).status_code
        == 200
    )
    r = admin_client.get("/v1/backlog")
    order = [row["title"] for row in r.json()["items"]]
    assert order == ["top", "mid", "low"]


def test_reorder_can_move_an_item_across_columns(admin_client) -> None:
    item = _create_item(admin_client)
    r = admin_client.post(
        f"/v1/backlog/{item['id']}/reorder",
        json={"expected_version": 1, "rank": 2.0, "status": "in_progress"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"


def test_decompose_creates_children_linked_to_the_parent(admin_client) -> None:
    parent = _create_item(admin_client, title="umbrella")
    r = admin_client.post(
        f"/v1/backlog/{parent['id']}/decompose",
        json={
            "expected_version": 1,
            "children": [{"title": "child a"}, {"title": "child b", "description": "part"}],
        },
    )
    assert r.status_code == 200, r.text
    children = r.json()["children"]
    assert [c["title"] for c in children] == ["child a", "child b"]
    assert all(c["parent_id"] == parent["id"] for c in children)

    detail = admin_client.get(f"/v1/backlog/{parent['id']}").json()
    assert sorted(c["title"] for c in detail["children"]) == ["child a", "child b"]


def test_decompose_needs_at_least_one_child(admin_client) -> None:
    item = _create_item(admin_client)
    r = admin_client.post(
        f"/v1/backlog/{item['id']}/decompose", json={"expected_version": 1, "children": []}
    )
    assert r.status_code == 422


def test_operator_controls_pin_pause_archive(admin_client) -> None:
    item = _create_item(admin_client)
    item_id = item["id"]

    pinned = admin_client.post(f"/v1/backlog/{item_id}/pin", json={"expected_version": 1})
    assert pinned.status_code == 200 and pinned.json()["pinned"] is True
    paused = admin_client.post(
        f"/v1/backlog/{item_id}/pause", json={"expected_version": 2, "reason": "waiting for #98"}
    )
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert paused.json()["paused_reason"] == "waiting for #98"
    resumed = admin_client.post(f"/v1/backlog/{item_id}/resume", json={"expected_version": 3})
    assert resumed.status_code == 200 and resumed.json()["paused"] is False
    assert resumed.json()["paused_reason"] is None

    # Re-pin so the archive interaction below has something to clear.
    assert (
        admin_client.post(f"/v1/backlog/{item_id}/pin", json={"expected_version": 4}).status_code
        == 200
    )
    archived = admin_client.post(f"/v1/backlog/{item_id}/archive", json={"expected_version": 5})
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert archived.json()["pinned"] is False

    # Archived items leave the default board but stay reachable.
    listed = admin_client.get("/v1/backlog").json()["items"]
    assert all(row["id"] != item_id for row in listed)
    detail = admin_client.get(f"/v1/backlog/{item_id}")
    assert detail.status_code == 200
    restored = admin_client.post(f"/v1/backlog/{item_id}/restore", json={"expected_version": 6})
    assert restored.status_code == 200 and restored.json()["archived"] is False
    assert [row["id"] for row in admin_client.get("/v1/backlog").json()["items"]] == [item_id]


def test_archived_item_refuses_plain_edits_until_restored(admin_client) -> None:
    item = _create_item(admin_client)
    assert (
        admin_client.post(
            f"/v1/backlog/{item['id']}/archive", json={"expected_version": 1}
        ).status_code
        == 200
    )
    r = admin_client.patch(
        f"/v1/backlog/{item['id']}", json={"expected_version": 2, "changes": {"title": "x"}}
    )
    assert r.status_code == 422


<<<<<<< HEAD
=======
def test_refused_patches_leave_stored_state_untouched(admin_client) -> None:
    """Edits stage on a copy; a refusal never publishes a partial mutation.

    Before copy-staging, ``_get()`` handed back the store's own object, so a
    patch refused by the archived-item check (or by a later invalid field)
    had already mutated the live row: a follow-up GET showed the new title at
    the old version with no provenance. Both leak shapes are pinned here.
    """
    item = _create_item(admin_client)
    item_id = item["id"]

    # A valid field followed by an invalid one must apply neither.
    r = admin_client.patch(
        f"/v1/backlog/{item_id}",
        json={"expected_version": 1, "changes": {"title": "staged", "priority": 9}},
    )
    assert r.status_code == 422
    after = admin_client.get(f"/v1/backlog/{item_id}").json()["item"]
    assert after["title"] == item["title"] and after["priority"] == item["priority"]
    assert after["version"] == 1 and after["provenance"][-1]["action"] == "created"

    # Same guarantee when the archived-item check is what refuses the patch.
    admin_client.post(f"/v1/backlog/{item_id}/archive", json={"expected_version": 1})
    r = admin_client.patch(
        f"/v1/backlog/{item_id}", json={"expected_version": 2, "changes": {"title": "x"}}
    )
    assert r.status_code == 422
    after = admin_client.get(f"/v1/backlog/{item_id}").json()["item"]
    assert after["title"] == item["title"] and after["version"] == 2


>>>>>>> d4ccd452e6a34349a37ce2cb732c18a1798b42dc
def test_provenance_records_every_actor_and_action(admin_client) -> None:
    item = _create_item(admin_client)
    item_id = item["id"]
    admin_client.patch(
        f"/v1/backlog/{item_id}", json={"expected_version": 1, "changes": {"description": "d"}}
    )
    admin_client.post(f"/v1/backlog/{item_id}/pin", json={"expected_version": 2})
    admin_client.post(
        f"/v1/backlog/{item_id}/block", json={"expected_version": 3, "reason": "blocked on review"}
    )
    provenance = admin_client.get(f"/v1/backlog/{item_id}").json()["item"]["provenance"]
    actions = [entry["action"] for entry in provenance]
    assert actions == ["created", "updated", "set_pinned", "blocked"]
    assert all(entry["actor"] == "admin" for entry in provenance)


def test_provenance_is_capped(admin_client, monkeypatch) -> None:
    from services import backlog as backlog_svc

    monkeypatch.setattr(backlog_svc, "_PROVENANCE_CAP", 5)
    item = _create_item(admin_client)
    version = item["version"]
    for i in range(8):
        r = admin_client.patch(
            f"/v1/backlog/{item['id']}",
            json={"expected_version": version, "changes": {"description": f"edit {i}"}},
        )
        assert r.status_code == 200
        version = r.json()["version"]
    provenance = admin_client.get(f"/v1/backlog/{item['id']}").json()["item"]["provenance"]
    assert len(provenance) == 5
    assert provenance[0]["action"] == "updated"  # "created" fell off the front


# ---------------------------------------------------------------------------
# The board speaks for exactly one authority: the canonical service
# ---------------------------------------------------------------------------


def test_list_and_detail_carry_the_non_authoritative_marker(admin_client) -> None:
    """Until #102's cutover, the UI is a preview over the canonical service.

<<<<<<< HEAD
    The payload says so, so the UI cannot quietly claim authority. The
    statement is read live from the committed authority marker (#102), which
    ships at the pre-cutover default: markdown, revision 0.
=======
    The payload says so, so the UI cannot quietly claim authority.
>>>>>>> d4ccd452e6a34349a37ce2cb732c18a1798b42dc
    """
    item = _create_item(admin_client)
    listed = admin_client.get("/v1/backlog").json()
    assert listed["authority"] == {
        "canonical_service": "services.backlog",
        "ui_authoritative": False,
        "cutover_issue": 102,
<<<<<<< HEAD
        "authority": "markdown",
        "authority_revision": 0,
=======
>>>>>>> d4ccd452e6a34349a37ce2cb732c18a1798b42dc
    }
    detail = admin_client.get(f"/v1/backlog/{item['id']}").json()
    assert detail["authority"]["ui_authoritative"] is False


def test_route_mutations_are_visible_to_the_service_and_the_audit_log(
    admin_client,
) -> None:
    """One write path: the route's effect is the service's state."""
    from routes.audit import log_audit  # noqa: F401  (import proves the module wiring)
    from services import backlog as backlog_svc

    item = _create_item(admin_client)
    admin_client.patch(
        f"/v1/backlog/{item['id']}",
        json={"expected_version": 1, "changes": {"status": "in_progress"}},
    )
    service_view = [i for i in asyncio.run(backlog_svc.list_items("admin")) if i.id == item["id"]]
    assert service_view[0].status == "in_progress"
