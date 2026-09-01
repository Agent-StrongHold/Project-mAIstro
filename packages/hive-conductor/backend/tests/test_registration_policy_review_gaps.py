"""Regression tests for security findings raised during #313 review."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient

_POLICY_KEY = "__registration_policy__"
_INVITE_PREFIX = "__registration_invite__:"


@pytest.fixture
def isolated_registration_review_state():
    import stores

    sessions = copy.deepcopy(dict(stores.sessions.items()))
    users = set(stores.users.keys())
    audit = copy.deepcopy(dict(stores.audit_log.items()))
    yield

    for key in list(stores.sessions.keys()):
        stores.sessions.pop(key, None)
    for key, value in sessions.items():
        stores.sessions[key] = value

    for user_id in list(stores.users.keys()):
        if user_id not in users:
            stores.users.pop(user_id, None)

    for key in list(stores.audit_log.keys()):
        stores.audit_log.pop(key, None)
    for key, value in audit.items():
        stores.audit_log[key] = value


def _register(client: TestClient, username: str, *, invite_token: str | None = None):
    body: dict[str, Any] = {
        "username": username,
        "password": "correct-horse-battery-staple",
        "confirm_password": "correct-horse-battery-staple",
    }
    if invite_token is not None:
        body["invite_token"] = invite_token
    return client.post("/v1/auth/register", json=body)


def test_open_policy_still_consumes_invite_and_audits_real_admin(
    isolated_registration_review_state, admin_client
) -> None:
    import stores
    from main import app

    opened = admin_client.put("/v1/settings/registration-policy", json={"mode": "open"})
    assert opened.status_code == 200

    issued = admin_client.post(
        "/v1/settings/registration-invitations",
        json={"ttl_seconds": 600},
    )
    assert issued.status_code == 200
    token = issued.json()["token"]

    policy_audits = [
        entry
        for entry in stores.audit_log.values()
        if entry.get("action") == "registration_policy_update"
    ]
    invite_audits = [
        entry
        for entry in stores.audit_log.values()
        if entry.get("action") == "registration_invitation_create"
    ]
    assert policy_audits[-1]["actor"] == "admin"
    assert invite_audits[-1]["actor"] == "admin"

    anonymous = TestClient(app)
    first = _register(anonymous, "open-invited-user", invite_token=token)
    assert first.status_code == 200

    closed = admin_client.put("/v1/settings/registration-policy", json={"mode": "closed"})
    assert closed.status_code == 200
    replay = _register(TestClient(app), "replay-after-close", invite_token=token)
    assert replay.status_code == 403


def test_failed_policy_persistence_restores_previous_local_value(monkeypatch) -> None:
    from services import registration_policy

    class PublishThenFailStore:
        def __init__(self) -> None:
            self._data = {_POLICY_KEY: {"mode": "closed", "updated_at": "before"}}

        def get(self, key: str, default: Any = None) -> Any:
            return self._data.get(key, default)

        def __setitem__(self, key: str, value: Any) -> None:
            self._data[key] = value
            raise OSError("durable writer unavailable")

    store = PublishThenFailStore()
    monkeypatch.setattr(registration_policy, "_kv", lambda: store)

    with pytest.raises(OSError, match="durable writer unavailable"):
        registration_policy.set_policy("open")

    assert store._data[_POLICY_KEY] == {"mode": "closed", "updated_at": "before"}
    assert registration_policy.get_policy() == {"mode": "closed"}
