"""Server-side session idle/absolute expiry contract for issue #1187."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import stores
from fastapi import Response
from fastapi.testclient import TestClient
from main import app
from routes import auth as auth_routes
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    current = datetime(2030, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(auth_routes, "_session_now", lambda: current)

    class Clock:
        value = current

        def advance(self, **delta: int) -> None:
            self.value = self.value + timedelta(**delta)
            monkeypatch.setattr(auth_routes, "_session_now", lambda: self.value)

    return Clock()


@pytest.fixture
def logged_in(clock) -> tuple[TestClient, str]:
    client = TestClient(app)
    response = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert response.status_code == 200, response.text
    session_id = client.cookies.get("hive_session")
    assert session_id
    yield client, session_id
    stores.sessions.pop(session_id, None)


def _session(session_id: str, *, created: datetime, last_activity: datetime) -> dict[str, Any]:
    return {
        "user_id": "user",
        "username": "testuser",
        "role": "user",
        "permissions": [],
        "elevated_grants": {},
        "created_at": created.isoformat(),
        "last_activity_at": last_activity.isoformat(),
    }


def test_login_persists_server_side_activity_and_reports_policy(
    logged_in: tuple[TestClient, str],
) -> None:
    client, session_id = logged_in
    record = stores.sessions[session_id]

    assert record["last_activity_at"] == record["created_at"]
    body = client.get("/v1/auth/whoami").json()
    policy = body["user"]["session_policy"]
    assert policy["idle_timeout_seconds"] == auth_routes._SESSION_IDLE_TIMEOUT
    assert policy["absolute_ttl_seconds"] == auth_routes._SESSION_ABSOLUTE_TTL
    assert policy["effective_expires_at"]
    assert session_id not in str(policy)


def test_absolute_expiry_is_denied_at_the_boundary(clock) -> None:
    session_id = "absolute-boundary"
    stores.sessions[session_id] = _session(
        session_id,
        created=clock.value - timedelta(seconds=auth_routes._SESSION_ABSOLUTE_TTL),
        last_activity=clock.value,
    )

    assert auth_routes.get_current_user(session_id) is None
    assert session_id not in stores.sessions


def test_idle_expiry_is_denied_at_the_boundary(clock) -> None:
    session_id = "idle-boundary"
    stores.sessions[session_id] = _session(
        session_id,
        created=clock.value,
        last_activity=clock.value - timedelta(seconds=auth_routes._SESSION_IDLE_TIMEOUT),
    )

    assert auth_routes.get_current_user(session_id) is None
    assert session_id not in stores.sessions


def test_clock_rollback_does_not_move_last_activity_backwards(clock) -> None:
    session_id = "clock-rollback"
    future_activity = clock.value + timedelta(seconds=10)
    stores.sessions[session_id] = _session(
        session_id,
        created=clock.value,
        last_activity=future_activity,
    )

    auth_routes._resolve_session(
        session_id,
        refresh_activity=True,
        now=clock.value + timedelta(seconds=1),
    )

    assert stores.sessions[session_id]["last_activity_at"] == future_activity.isoformat()
    stores.sessions.pop(session_id, None)


def test_whoami_is_observational_and_cannot_keep_an_idle_session_alive(
    logged_in: tuple[TestClient, str], clock
) -> None:
    client, session_id = logged_in
    original_activity = stores.sessions[session_id]["last_activity_at"]

    clock.advance(seconds=auth_routes._SESSION_IDLE_TIMEOUT - 1)
    assert client.get("/v1/auth/whoami").json()["authenticated"] is True
    assert stores.sessions[session_id]["last_activity_at"] == original_activity

    clock.advance(seconds=1)
    assert client.get("/v1/auth/whoami").json()["authenticated"] is False
    assert session_id not in stores.sessions


def test_authenticated_api_activity_slides_idle_expiry_but_not_absolute_expiry(
    logged_in: tuple[TestClient, str], clock
) -> None:
    client, session_id = logged_in
    clock.advance(seconds=auth_routes._SESSION_IDLE_TIMEOUT - 1)

    response = client.get("/v1/tasks")
    assert response.status_code == 200, response.text
    refreshed_activity = stores.sessions[session_id]["last_activity_at"]
    assert refreshed_activity == clock.value.isoformat()

    clock.advance(seconds=auth_routes._SESSION_IDLE_TIMEOUT - 1)
    assert client.get("/v1/auth/whoami").json()["authenticated"] is True

    clock.value = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(
        seconds=auth_routes._SESSION_ABSOLUTE_TTL
    )
    assert client.get("/v1/auth/whoami").json()["authenticated"] is False
    assert session_id not in stores.sessions


def test_rejected_authenticated_polling_does_not_refresh_idle_expiry(
    logged_in: tuple[TestClient, str], clock
) -> None:
    client, session_id = logged_in
    original_activity = stores.sessions[session_id]["last_activity_at"]

    clock.advance(seconds=auth_routes._SESSION_IDLE_TIMEOUT - 1)
    response = client.get("/v1/harness")
    assert response.status_code == 403
    assert stores.sessions[session_id]["last_activity_at"] == original_activity

    clock.advance(seconds=1)
    assert client.get("/v1/auth/whoami").json()["authenticated"] is False
    assert session_id not in stores.sessions


def test_rejected_websocket_handshake_does_not_refresh_idle_expiry(
    logged_in: tuple[TestClient, str], clock
) -> None:
    client, session_id = logged_in
    original_activity = stores.sessions[session_id]["last_activity_at"]

    clock.advance(seconds=auth_routes._SESSION_IDLE_TIMEOUT - 1)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/v1/ws/dags/whatever/run") as websocket,
    ):
        websocket.receive_json()

    assert exc.value.code == 1008
    assert stores.sessions[session_id]["last_activity_at"] == original_activity

    clock.advance(seconds=1)
    assert client.get("/v1/auth/whoami").json()["authenticated"] is False
    assert session_id not in stores.sessions


def test_revocation_mid_handshake_denies_without_refreshing_idle_expiry(
    logged_in: tuple[TestClient, str], clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `dags.write` elevation withdrawn between the handshake's admission
    check and its post-authorization activity touch must deny the handshake
    AND leave the idle window untouched (#1187).

    The DAG-run socket authorizes in two phases; the activity touch used to
    happen inside the same re-resolve as the phase-2 permission re-check, so a
    handshake denied by a mid-handshake revocation still slid the idle window.
    Denial is not eligible activity no matter which side wins that race, and
    the ordering must match the HTTP middleware's resolve -> authorize ->
    touch sequence.
    """
    import routes.ws as ws_routes

    client, session_id = logged_in
    sess = stores.sessions[session_id]
    stores.sessions[session_id] = {**sess, "elevated_grants": {"task-1": ["dags.write"]}}
    user = stores.users["user"]
    stores.users["user"] = user.model_copy(update={"permissions": ["dags.write"]})

    checks = {"count": 0}

    def revoked_after_admission(user: dict, perm: str) -> bool:
        checks["count"] += 1
        # Admission passes; the re-check after workspace-scope admission sees
        # the withdrawn elevation.
        return checks["count"] == 1

    monkeypatch.setattr(ws_routes, "principal_has_permission", revoked_after_admission)

    workspace_id = client.post(
        "/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": "idle policy"}
    ).json()["id"]

    # Advance inside the idle window so a refresh would be observable.
    clock.advance(seconds=60)
    original_activity = stores.sessions[session_id]["last_activity_at"]

    try:
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            client.websocket_connect(
                f"/v1/ws/dags/no-such-dag/run?workspace_id={workspace_id}"
            ) as websocket,
        ):
            websocket.receive_json()

        assert exc.value.code == 1008
        assert checks["count"] == 2
        assert stores.sessions[session_id]["last_activity_at"] == original_activity
        # Denial did not kill the session either: it stays valid for eligible
        # activity until its own expiry.
        assert client.get("/v1/auth/whoami").json()["authenticated"] is True
    finally:
        stores.users["user"] = user


def test_accepted_websocket_handshake_is_eligible_activity(
    logged_in: tuple[TestClient, str], clock
) -> None:
    """Control for the denial tests: an accepted handshake IS eligible activity
    and slides the idle window (ADR-077), while the absolute cap stays put."""
    client, session_id = logged_in

    clock.advance(seconds=60)
    with (
        client.websocket_connect("/v1/ws/tasks/unknown-task") as websocket,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        websocket.receive_json()

    # Clean close (1000), not policy rejection: the socket ran.
    assert exc.value.code != 1008
    assert stores.sessions[session_id]["last_activity_at"] == clock.value.isoformat()
    assert (
        stores.sessions[session_id]["created_at"] != stores.sessions[session_id]["last_activity_at"]
    )


def test_deactivation_takes_effect_for_an_existing_session(
    logged_in: tuple[TestClient, str],
) -> None:
    client, session_id = logged_in
    user = stores.users["user"]
    stores.users["user"] = user.model_copy(update={"is_active": False})
    try:
        assert client.get("/v1/tasks").status_code == 401
        assert session_id not in stores.sessions
        stores.users["user"] = user
        assert client.get("/v1/auth/whoami").json()["authenticated"] is False
    finally:
        stores.users["user"] = user
        stores.sessions.pop(session_id, None)


def test_explicit_session_revocation_takes_effect_immediately(
    logged_in: tuple[TestClient, str],
) -> None:
    client, session_id = logged_in
    stores.sessions.pop(session_id)

    assert client.get("/v1/tasks").status_code == 401
    assert client.get("/v1/auth/whoami").json()["authenticated"] is False


# --- Non-session store records must survive forged session cookies (#1187) ---
#
# The sessions store is a shared KV: the setup wizard keeps its durable
# one-shot first-run claim and its completed-setup config marker there, and
# neither record has a session shape. Resolution and logout therefore fail
# closed WITHOUT deleting records they do not recognize — otherwise an
# unauthenticated request naming a marker in its session cookie could evict
# the boundary that keeps a second /v1/setup/complete from minting a
# competing admin account.

_CLAIM = {"claimed_at": "2030-01-01T00:00:00+00:00"}


def test_resolution_denies_but_never_deletes_non_session_records() -> None:
    from routes.setup import _SETUP_CLAIM_KEY, _SETUP_KEY

    stores.sessions[_SETUP_CLAIM_KEY] = dict(_CLAIM)
    stores.sessions[_SETUP_KEY] = {"completed_at": "2030-01-01T00:00:00+00:00"}
    try:
        assert auth_routes._resolve_session(_SETUP_CLAIM_KEY) is None
        assert auth_routes._resolve_session(_SETUP_KEY) is None
        # Denied for authentication purposes, yet both markers remain.
        assert _SETUP_CLAIM_KEY in stores.sessions
        assert _SETUP_KEY in stores.sessions
        # ... and the one-shot insert boundary still holds against a rival.
        assert stores.sessions.put_if_absent(_SETUP_CLAIM_KEY, dict(_CLAIM)) is False
    finally:
        stores.sessions.pop(_SETUP_CLAIM_KEY, None)
        stores.sessions.pop(_SETUP_KEY, None)


def test_forged_marker_cookie_through_the_middleware_releases_nothing() -> None:
    """End-to-end: an unauthenticated request whose session cookie names the
    setup claim gets 401 and leaves first-run one-shot semantics intact."""
    from routes.setup import _SETUP_CLAIM_KEY, _is_setup_complete

    stores.sessions[_SETUP_CLAIM_KEY] = dict(_CLAIM)
    try:
        client = TestClient(app)
        assert (
            client.get("/v1/tasks", cookies={"hive_session": _SETUP_CLAIM_KEY}).status_code == 401
        )
        assert (
            client.get("/v1/auth/whoami", cookies={"hive_session": _SETUP_CLAIM_KEY}).json()[
                "authenticated"
            ]
            is False
        )
        assert _SETUP_CLAIM_KEY in stores.sessions
        assert _is_setup_complete() is True
        assert stores.sessions.put_if_absent(_SETUP_CLAIM_KEY, dict(_CLAIM)) is False
    finally:
        stores.sessions.pop(_SETUP_CLAIM_KEY, None)


def test_logout_cannot_delete_the_setup_claim_marker() -> None:
    """Logout is authenticated, so a forged-cookie logout is refused at the
    middleware — and the route's own pop (reachable via direct callers) must
    only ever evict records that resolved as live sessions."""
    from routes.setup import _SETUP_CLAIM_KEY, _is_setup_complete

    stores.sessions[_SETUP_CLAIM_KEY] = dict(_CLAIM)
    try:
        client = TestClient(app)
        # Over HTTP the middleware refuses the request outright...
        response = client.post("/v1/auth/logout", cookies={"hive_session": _SETUP_CLAIM_KEY})
        assert response.status_code == 401
        assert _SETUP_CLAIM_KEY in stores.sessions
        # ... and invoking the route directly (no middleware) still refuses to
        # delete the marker: only resolved sessions are evicted.
        assert auth_routes.logout(Response(), hive_session=_SETUP_CLAIM_KEY)["ok"] is True
        assert _SETUP_CLAIM_KEY in stores.sessions
        assert _is_setup_complete() is True
    finally:
        stores.sessions.pop(_SETUP_CLAIM_KEY, None)


def test_logout_still_invalidates_a_live_session() -> None:
    """Control for the logout guard: a real session is still evicted."""
    client = TestClient(app)
    assert (
        client.post(
            "/v1/auth/login", json={"username": "testuser", "password": "testpass"}
        ).status_code
        == 200
    )
    session_id = client.cookies.get("hive_session")
    assert session_id

    assert client.post("/v1/auth/logout").json()["ok"] is True
    assert session_id not in stores.sessions
    assert client.get("/v1/auth/whoami").json()["authenticated"] is False


def test_records_from_before_idle_expiry_are_active_at_creation_and_bounded(clock) -> None:
    """Records written before idle expiry shipped carry no last_activity_at.

    ADR-077: they are treated as having been active at creation — admitted
    inside a creation-anchored idle window, never granted an unbounded
    lifetime by the missing timestamp.
    """
    session_id = "legacy-record"
    record = _session(session_id, created=clock.value, last_activity=clock.value)
    del record["last_activity_at"]
    stores.sessions[session_id] = record

    clock.advance(seconds=auth_routes._SESSION_IDLE_TIMEOUT - 1)
    assert auth_routes.get_current_user(session_id) is not None

    clock.advance(seconds=1)
    assert auth_routes.get_current_user(session_id) is None
    assert session_id not in stores.sessions


def test_activity_refresh_fails_closed_on_an_empty_session_id(clock) -> None:
    """The refresh helper denies without a session id: no crash, no admission."""
    assert auth_routes.refresh_session_activity(None) is False
    assert auth_routes.refresh_session_activity("") is False


def test_a_session_that_cannot_produce_expiries_is_denied_not_served(
    logged_in: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense in depth at the last gate before the user dict is built: when
    the expiry computation yields nothing, the session is denied rather than
    served with unbounded authority. Simulated by the timestamps becoming
    unreadable between the resolving decision and the re-check."""
    _client, session_id = logged_in
    real = auth_routes._session_expiries
    calls = {"count": 0}

    def torn(sess: dict[str, Any], now: datetime) -> tuple[datetime, datetime] | None:
        calls["count"] += 1
        result = real(sess, now)
        return None if calls["count"] >= 2 else result

    monkeypatch.setattr(auth_routes, "_session_expiries", torn)
    assert auth_routes.get_current_user(session_id) is None
    # Denial without destruction: cleanup stays the normal expiry path's job.
    assert session_id in stores.sessions


def test_user_has_permission_fails_closed_on_missing_or_dead_accounts(clock) -> None:
    """The policy lookup answers no for a deleted or deactivated account even
    while the session record itself still resolves."""
    session_id = "perm-lookup"
    stores.sessions[session_id] = _session(
        session_id, created=clock.value, last_activity=clock.value
    )
    user = stores.users["user"]
    try:
        stores.users["user"] = user.model_copy(update={"permissions": ["dags.read"]})
        # Control: a live session over a live account answers the question.
        assert auth_routes.user_has_permission(session_id, "dags.read") is True
        # A deleted account row answers no.
        stores.users.pop("user")
        assert auth_routes.user_has_permission(session_id, "dags.read") is False
        # A deactivated account answers no even though the session resolves.
        stores.users["user"] = user.model_copy(update={"is_active": False})
        assert auth_routes.user_has_permission(session_id, "dags.read") is False
    finally:
        stores.users["user"] = user
        stores.sessions.pop(session_id, None)
    assert auth_routes.user_has_permission("no-such-session", "dags.read") is False


def test_revoking_elevation_from_unknown_sessions_or_tasks_is_a_noop(clock) -> None:
    """Revocation is idempotent: neither an unknown session nor an unknown
    task writes anything, so a stale revoke cannot create state."""
    session_id = "revoke-noop"
    stores.sessions[session_id] = _session(
        session_id, created=clock.value, last_activity=clock.value
    )
    before = dict(stores.sessions[session_id])

    auth_routes.revoke_task_elevation("no-such-session", "task-1")
    auth_routes.revoke_task_elevation(session_id, "no-such-task")
    assert stores.sessions[session_id] == before
    stores.sessions.pop(session_id, None)


def test_elevate_denies_requests_without_a_live_session() -> None:
    """Elevation requires a session that resolves: none at all, or one that
    expired/revoked/forged, both end in 401 before any password work."""
    client = TestClient(app)
    body = {"password": "testpass", "task_id": "task-1"}
    assert client.post("/v1/auth/elevate", json=body).status_code == 401

    client.cookies.set("hive_session", "forged-or-expired")
    response = client.post("/v1/auth/elevate", json=body)
    assert response.status_code == 401
    assert "forged-or-expired" not in stores.sessions


def test_elevate_cannot_overwrite_a_concurrent_logout(
    logged_in: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The elevation write re-reads the session under the lock: a logout (or
    purge) winning that race must end in 401, not in a resurrected record
    carrying fresh grants."""
    client, session_id = logged_in
    real_verify = auth_routes.equal_cost_verify
    reached = {"verify": False}

    def logout_wins_mid_request(*args: Any, **kwargs: Any) -> bool:
        result = real_verify(*args, **kwargs)
        reached["verify"] = True
        # The concurrent logout deletes the record after the route's first
        # resolve and before the locked re-read.
        stores.sessions.pop(session_id, None)
        return result

    monkeypatch.setattr(auth_routes, "equal_cost_verify", logout_wins_mid_request)
    response = client.post("/v1/auth/elevate", json={"password": "testpass", "task_id": "task-1"})
    # The 401 comes from the locked re-read: the flow passed password
    # verification, where the logout won, and the elevation was refused.
    assert reached["verify"] is True
    assert response.status_code == 401, response.text
    assert session_id not in stores.sessions


def test_the_middleware_touch_losing_the_race_denies_the_request(
    logged_in: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-077: revocation wins over a concurrent activity update. When the
    serialized touch fails after the request resolved — expiry or revocation
    won between resolve and touch — the request is denied with 401 rather
    than served on a session that no longer exists."""
    client, session_id = logged_in
    original_activity = stores.sessions[session_id]["last_activity_at"]
    monkeypatch.setattr(auth_routes, "refresh_session_activity", lambda sid: False)

    response = client.get("/v1/tasks")

    assert response.status_code == 401
    assert stores.sessions[session_id]["last_activity_at"] == original_activity


def test_handshake_denied_when_the_session_dies_before_the_recheck(
    logged_in: tuple[TestClient, str], clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session revoked (or expired) between the handshake's admission check
    and the activity re-check is denied at the re-check — a denial that
    happens before the serialized touch is not activity and slides nothing."""
    import routes.ws as ws_routes

    client, session_id = logged_in
    real = ws_routes.resolve_principal
    calls = {"count": 0}

    def revoked_mid_handshake(
        cookies: object, authorization: object, *, refresh_activity: bool = False
    ) -> dict | None:
        calls["count"] += 1
        if calls["count"] == 2:
            # Admission (call 1, in _authenticate) passed; revocation wins
            # before the re-check (call 2, the non-refreshing resolve).
            stores.sessions.pop(session_id, None)
        return real(cookies, authorization, refresh_activity=refresh_activity)

    monkeypatch.setattr(ws_routes, "resolve_principal", revoked_mid_handshake)

    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/v1/ws/tasks/whatever") as websocket,
    ):
        websocket.receive_json()

    assert exc.value.code == 1008
    assert session_id not in stores.sessions


def test_handshake_denied_when_revocation_wins_before_the_touch(
    logged_in: tuple[TestClient, str], clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The serialized touch re-validates the record under the session lock:
    revocation winning between the authorization decision and the touch
    denies the handshake and leaves nothing to resurrect."""
    import routes.ws as ws_routes

    client, session_id = logged_in
    real = ws_routes.resolve_principal

    def revoked_at_touch(
        cookies: object, authorization: object, *, refresh_activity: bool = False
    ) -> dict | None:
        if refresh_activity:
            stores.sessions.pop(session_id, None)
        return real(cookies, authorization, refresh_activity=refresh_activity)

    monkeypatch.setattr(ws_routes, "resolve_principal", revoked_at_touch)

    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/v1/ws/tasks/whatever") as websocket,
    ):
        websocket.receive_json()

    assert exc.value.code == 1008
    assert session_id not in stores.sessions


def test_corrupt_session_records_are_still_evicted() -> None:
    """The eviction branch stays reachable for session-shaped records: a real
    session whose timestamps became unparseable is cleaned up, while the
    marker records (no session shape at all) never enter that branch."""
    from routes.setup import _SETUP_CLAIM_KEY

    session_id = "corrupt-created-at"
    stores.sessions[session_id] = {
        "user_id": "user",
        "created_at": "not-a-timestamp",
        "last_activity_at": "also-not-a-timestamp",
    }
    stores.sessions[_SETUP_CLAIM_KEY] = {"claimed_at": "not-a-timestamp"}
    try:
        assert auth_routes._resolve_session(session_id) is None
        assert session_id not in stores.sessions
        assert _SETUP_CLAIM_KEY in stores.sessions
    finally:
        stores.sessions.pop(session_id, None)
        stores.sessions.pop(_SETUP_CLAIM_KEY, None)
