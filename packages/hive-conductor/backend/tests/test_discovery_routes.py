"""Workspace discovery routes (#1051) — the HTTP face of bounded discovery.

Driven against the app like every other route suite, over the real canonical
Workspace authority and the discovery service's durable store, with the
canonical Run trigger faked at its one seam (`services.dag_agents.
run_registered_dag`) — the same contract `test_discovery_service.py` uses one
level down. What these pin over HTTP:

- fail-closed authorization on every route: anonymous 401, non-member 404
  (identical to a missing Workspace — no existence oracle), viewer member
  403 on writes while reads stay allowed;
- the config contract: defaults when unsaved, partial updates that persist,
  unknown fields and bad values refused with 422;
- the trigger contract: a disabled or budget-exhausted Workspace is a clean
  409 (never a 500, never a silent no-op), a successful trigger returns the
  canonical run id with its lifted surfaced count;
- the items/status contract: the surfaced set reads the service (small, with
  budget evidence), feedback keeps/dismisses through the same route an
  Agent's tool would use, with 404 for an unknown fingerprint and 422 for a
  malformed action.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import stores
from fastapi.testclient import TestClient
from main import app
from services import attention, discovery


@pytest.fixture(autouse=True)
def _clean_discovery_state():
    keys = list(discovery.store.keys())
    for key in keys:
        discovery.store.pop(key)
    yield
    for key in list(discovery.store.keys()):
        discovery.store.pop(key)


@pytest.fixture
def fake_dag_runner(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The canonical trigger seam, faked: an empty completed cycle.

    The same contract `test_discovery_service.py` fakes one level down —
    the cycle's physical work is proven on the canonical spine in the core
    suite; here the route only needs the Run it must report.
    """

    async def _fake_run_registered_dag(dag_id: str, **kwargs: Any) -> tuple[Any, Any]:
        return SimpleNamespace(), SimpleNamespace(
            run=SimpleNamespace(run_id="run-http-1", status=SimpleNamespace(value="completed")),
            node_runs=(),
        )

    from services import dag_agents

    monkeypatch.setattr(dag_agents, "run_registered_dag", _fake_run_registered_dag)
    return SimpleNamespace(run_id="run-http-1")


def _charge_cycle(ws: str, run_id: str) -> None:
    """Charge the cycle ledger the way the real nodes do at execution time."""
    provider = discovery.discovery_context_provider()
    asyncio.run(provider.context_for(ws, ws, "admin", cycle_key=run_id))


def _create_workspace(admin_client: TestClient, name: str = "Discovery WS") -> str:
    r = admin_client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_member(admin_client: TestClient, workspace_id: str, user_id: str, role: str) -> None:
    r = admin_client.post(
        f"/v1/workspaces/{workspace_id}/members", json={"user_id": user_id, "role": role}
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


def _enable(ws: str, **overrides: Any) -> None:
    changes = {"enabled": True, "watch_topics": ["camera"], **overrides}
    discovery.update_config(ws, changes, actor="admin")


def _curated_row(fingerprint: str, title: str, *, score: float = 0.8) -> dict[str, Any]:
    return {
        "fingerprint": fingerprint,
        "entry_id": fingerprint,
        "url": f"https://source.example.com/{fingerprint}",
        "title": title,
        "summary": "a curated summary",
        "category": "deals",
        "source_url": "https://feeds.example.com/rss",
        "published_at": "2026-11-25T10:00:00+00:00",
        "expires_at": "",
        "relevance": 0.9,
        "novelty": 0.8,
        "confidence": 0.9,
        "score": score,
        "strategy": "lexical",
        "explain": "matched watch topics: camera",
        "matched_topics": ["camera"],
        "run_id": "run-1",
    }


def _surface(ws: str, fingerprint: str, title: str, *, score: float = 0.8) -> None:
    row = _curated_row(fingerprint, title, score=score)
    discovery.store[discovery._item_key(ws, fingerprint)] = {
        **row,
        "status": "surfaced",
        "surfaced_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# Fail-closed authorization — every route, one contract
# ---------------------------------------------------------------------------


def test_anonymous_callers_get_401_on_every_discovery_route(admin_client: TestClient) -> None:
    ws = _create_workspace(admin_client)
    anon = TestClient(app)
    assert anon.get(f"/v1/workspaces/{ws}/discovery/config").status_code == 401
    assert (
        anon.put(f"/v1/workspaces/{ws}/discovery/config", json={"enabled": True}).status_code == 401
    )
    assert anon.post(f"/v1/workspaces/{ws}/discovery/run", json={}).status_code == 401
    assert anon.get(f"/v1/workspaces/{ws}/discovery/items").status_code == 401
    assert anon.get(f"/v1/workspaces/{ws}/discovery/status").status_code == 401
    assert (
        anon.post(
            f"/v1/workspaces/{ws}/discovery/items/fp/feedback", json={"action": "keep"}
        ).status_code
        == 401
    )


def test_a_non_member_and_a_missing_workspace_look_identical(
    admin_client: TestClient, authed_client: TestClient
) -> None:
    """No existence oracle: stranger and missing id both answer 404 on the
    member-scoped reads and on the feedback write. The config/run writes are
    additionally gated by the app-level workspaces.write permission, so a
    non-admin stranger is refused there before membership is consulted."""
    ws = _create_workspace(admin_client)
    ghost = "ws-that-does-not-exist"
    for target in (ws, ghost):
        assert authed_client.get(f"/v1/workspaces/{target}/discovery/config").status_code == 404
        assert authed_client.get(f"/v1/workspaces/{target}/discovery/items").status_code == 404
        assert authed_client.get(f"/v1/workspaces/{target}/discovery/status").status_code == 404
        assert (
            authed_client.post(
                f"/v1/workspaces/{target}/discovery/items/fp/feedback", json={"action": "keep"}
            ).status_code
            == 404
        )
    # The permission gate refuses a non-writer before the membership check.
    assert (
        authed_client.put(
            f"/v1/workspaces/{ws}/discovery/config", json={"enabled": True}
        ).status_code
        == 403
    )
    assert authed_client.post(f"/v1/workspaces/{ws}/discovery/run", json={}).status_code == 403
    # For a writer who is not a member, the membership check answers the
    # identical 404 — the stranger and the ghost are indistinguishable.
    assert admin_client.post(f"/v1/workspaces/{ghost}/discovery/run", json={}).status_code == 404
    assert (
        admin_client.put(
            f"/v1/workspaces/{ghost}/discovery/config", json={"enabled": True}
        ).status_code
        == 404
    )


def test_a_viewer_member_reads_but_cannot_change_discovery(
    admin_client: TestClient, authed_client: TestClient
) -> None:
    """The route's own authority: a writer-permission holder who is only a
    VIEWER member is refused 403 by the discovery routes themselves — the
    read-only line the route docstring promises."""
    user_row = stores.users.get("user")
    assert user_row is not None
    original_permissions = list(user_row.permissions)
    user_row.permissions = ["workspaces.write"]
    try:
        # Assign the permission and elevate it for the session, so the
        # app-level gate passes and the route-level membership check is what
        # answers — the layer this test exists to pin.
        r = authed_client.post(
            "/v1/auth/elevate",
            json={"password": "testpass", "permissions": ["workspaces.write"], "task_id": "t1"},
        )
        assert r.status_code == 200, r.text

        ws = _create_workspace(admin_client, name="Viewer WS")
        _add_member(admin_client, ws, "user", "viewer")
        # A viewer member reads every projection.
        assert authed_client.get(f"/v1/workspaces/{ws}/discovery/config").status_code == 200
        assert authed_client.get(f"/v1/workspaces/{ws}/discovery/items").status_code == 200
        assert authed_client.get(f"/v1/workspaces/{ws}/discovery/status").status_code == 200

        _surface(ws, "fp-view", "Visible to viewer")
        r = authed_client.put(f"/v1/workspaces/{ws}/discovery/config", json={"enabled": True})
        assert r.status_code == 403
        assert "read-only" in r.json()["detail"]
        r = authed_client.post(f"/v1/workspaces/{ws}/discovery/run", json={})
        assert r.status_code == 403
        assert "read-only" in r.json()["detail"]
        r = authed_client.post(
            f"/v1/workspaces/{ws}/discovery/items/fp-view/feedback", json={"action": "keep"}
        )
        assert r.status_code == 403
        assert "read-only" in r.json()["detail"]
    finally:
        user_row.permissions = original_permissions


# ---------------------------------------------------------------------------
# Config over HTTP: defaults, partial updates, 422 on bad values
# ---------------------------------------------------------------------------


def test_an_unconfigured_workspace_reads_the_disabled_defaults(
    admin_client: TestClient, authed_client: TestClient
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    body = authed_client.get(f"/v1/workspaces/{ws}/discovery/config").json()
    assert body["enabled"] is False
    assert body["max_surfaced"] == discovery.DEFAULT_CONFIG["max_surfaced"]
    assert body["source_binding_id"] == ""


def test_a_partial_config_update_changes_only_the_given_fields(
    admin_client: TestClient,
) -> None:
    ws = _create_workspace(admin_client)
    r = admin_client.put(
        f"/v1/workspaces/{ws}/discovery/config",
        json={"enabled": True, "watch_topics": ["camera", "lens"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["watch_topics"] == ["camera", "lens"]
    # Fields the update omitted keep their defaults.
    assert body["max_surfaced"] == discovery.DEFAULT_CONFIG["max_surfaced"]
    assert body["updated_by"]  # the authenticated actor is recorded


def test_bad_config_values_are_a_422(admin_client: TestClient) -> None:
    ws = _create_workspace(admin_client)
    r = admin_client.put(f"/v1/workspaces/{ws}/discovery/config", json={"max_surfaced": 500})
    assert r.status_code == 422
    assert "max_surfaced" in r.json()["detail"]
    r = admin_client.put(f"/v1/workspaces/{ws}/discovery/config", json={"watch_topics": "camera"})
    assert r.status_code == 422
    # Unknown fields are ignored by the body model (forward-compatible PUTs),
    # so an unknown field cannot corrupt config through HTTP.
    r = admin_client.put(f"/v1/workspaces/{ws}/discovery/config", json={"crawl_the_web": True})
    assert r.status_code == 200
    assert "crawl_the_web" not in admin_client.get(f"/v1/workspaces/{ws}/discovery/config").json()


# ---------------------------------------------------------------------------
# Trigger over HTTP: 409 on refusal, 200 with the canonical run id
# ---------------------------------------------------------------------------


def test_triggering_a_disabled_workspace_is_a_clean_409(
    admin_client: TestClient,
    fake_dag_runner: Any,
) -> None:
    ws = _create_workspace(admin_client)
    r = admin_client.post(f"/v1/workspaces/{ws}/discovery/run", json={})
    assert r.status_code == 409
    assert "discovery_disabled" in r.json()["detail"]


def test_a_successful_trigger_returns_the_run_and_lifted_count(
    admin_client: TestClient,
    authed_client: TestClient,
    fake_dag_runner: Any,
) -> None:
    ws = _create_workspace(admin_client)
    _enable(ws)
    r = admin_client.post(f"/v1/workspaces/{ws}/discovery/run", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == "run-http-1"
    assert body["status"] == "completed"
    assert body["surfaced"] == 0  # the fake cycle carried no candidates


def test_trigger_refuses_with_409_when_the_budget_is_spent(
    admin_client: TestClient,
    authed_client: TestClient,
    fake_dag_runner: Any,
) -> None:
    ws = _create_workspace(admin_client)
    _enable(ws, daily_curate_budget=1)
    first = admin_client.post(f"/v1/workspaces/{ws}/discovery/run", json={})
    assert first.status_code == 200
    _charge_cycle(ws, str(first.json()["run_id"]))
    r = admin_client.post(f"/v1/workspaces/{ws}/discovery/run", json={})
    assert r.status_code == 409
    assert "discovery_cycle_budget_exhausted" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Items, feedback, status over HTTP
# ---------------------------------------------------------------------------


def test_surfaced_items_read_small_with_budget_evidence(
    admin_client: TestClient, authed_client: TestClient
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "viewer")
    _surface(ws, "fp-1", "Tripod review", score=0.9)
    _surface(ws, "fp-2", "Lens deal", score=0.7)

    body = authed_client.get(f"/v1/workspaces/{ws}/discovery/items").json()
    assert [item["fingerprint"] for item in body["items"]] == ["fp-1", "fp-2"]
    assert body["counts"]["surfaced"] == 2
    assert body["counts"]["shown"] == 2
    assert body["budget"]["daily_fetch_budget"] == discovery.DEFAULT_CONFIG["daily_fetch_budget"]


def test_feedback_keeps_and_dismisses_and_refuses_malformed_actions(
    admin_client: TestClient, authed_client: TestClient
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "editor")
    _surface(ws, "fp-keep", "Keep me")
    _surface(ws, "fp-hide", "Hide me")

    r = authed_client.post(
        f"/v1/workspaces/{ws}/discovery/items/fp-keep/feedback", json={"action": "keep"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "kept"

    r = authed_client.post(
        f"/v1/workspaces/{ws}/discovery/items/fp-hide/feedback", json={"action": "dismiss"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"
    # The dismissal shaped the Attention projection too — one action, one
    # canonical state.
    assert ("discovery_item", "fp-hide") in attention.dismissed_source_ids(ws)

    r = authed_client.post(
        f"/v1/workspaces/{ws}/discovery/items/fp-keep/feedback", json={"action": "purge"}
    )
    assert r.status_code == 422
    r = authed_client.post(
        f"/v1/workspaces/{ws}/discovery/items/fp-ghost/feedback", json={"action": "keep"}
    )
    assert r.status_code == 404

    # A dismissed item no longer shows in the surfaced set; the kept item
    # leaves the surface too — the surfaced set is the untouched small set,
    # and keep vs dismiss differ in Attention (kept stays visible there).
    items = authed_client.get(f"/v1/workspaces/{ws}/discovery/items").json()
    assert items["items"] == []
    assert items["counts"]["dismissed"] == 2
    assert ("discovery_item", "fp-keep") not in attention.dismissed_source_ids(ws)
    assert ("discovery_item", "fp-hide") in attention.dismissed_source_ids(ws)


def test_status_reports_config_budget_preferences_and_the_dag_id(
    admin_client: TestClient, authed_client: TestClient
) -> None:
    ws = _create_workspace(admin_client)
    _add_member(admin_client, ws, "user", "viewer")
    _enable(ws, watch_topics=["camera", "lens"])
    body = authed_client.get(f"/v1/workspaces/{ws}/discovery/status").json()
    assert body["workspace_id"] == ws
    assert body["config"]["enabled"] is True
    assert body["budget"]["daily_curate_budget"] == discovery.DEFAULT_CONFIG["daily_curate_budget"]
    assert body["preferences"] == {}
    assert body["dag_id"] == discovery.DISCOVERY_DAG_ID


# ---------------------------------------------------------------------------
# The gate vs. the service: membership revoked in between answers 404
# ---------------------------------------------------------------------------


def test_a_membership_revoked_between_the_gate_and_the_service_is_a_404(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both the route gate and the service re-check membership; a revocation
    landing between them (a concurrent demotion/removal) surfaces as the same
    404, never a partial read or write."""
    import services.workspace_authority as authority
    from routes import discovery as discovery_routes

    ws = _create_workspace(admin_client)
    real_visible_view = authority.visible_view
    calls = {"n": 0}

    async def flaky_visible_view(user_id: str, workspace_id: str):
        calls["n"] += 1
        if calls["n"] == 1:
            return await real_visible_view(user_id, workspace_id)
        return None  # revoked after the gate let the request in

    monkeypatch.setattr(authority, "visible_view", flaky_visible_view)
    monkeypatch.setattr(discovery_routes, "visible_view", flaky_visible_view)

    r = admin_client.post(f"/v1/workspaces/{ws}/discovery/run", json={})
    assert r.status_code == 404
    assert r.json()["detail"] == "workspace not found"

    calls["n"] = 0
    r = admin_client.get(f"/v1/workspaces/{ws}/discovery/items")
    assert r.status_code == 404
    assert r.json()["detail"] == "workspace not found"
