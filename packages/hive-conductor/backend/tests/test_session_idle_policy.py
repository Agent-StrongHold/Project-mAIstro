"""Server-side session idle/absolute expiry contract for issue #1187."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import stores
from fastapi.testclient import TestClient
from main import app
from routes import auth as auth_routes


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


def test_deactivation_takes_effect_for_an_existing_session(
    logged_in: tuple[TestClient, str],
) -> None:
    client, session_id = logged_in
    user = stores.users["user"]
    stores.users["user"] = user.model_copy(update={"is_active": False})
    try:
        assert client.get("/v1/tasks").status_code == 401
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
