"""Behavioral regression coverage for fail-closed registration policy (#313)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

_POLICY_KEY = "__registration_policy__"
_INVITE_PREFIX = "__registration_invite__:"


@pytest.fixture
def isolated_registration_state():
    import stores

    original_policy = {
        key: stores.sessions[key]
        for key in list(stores.sessions.keys())
        if key == _POLICY_KEY or key.startswith(_INVITE_PREFIX)
    }
    original_users = set(stores.users.keys())
    for key in list(stores.sessions.keys()):
        if key == _POLICY_KEY or key.startswith(_INVITE_PREFIX):
            stores.sessions.pop(key, None)
    yield
    for key in list(stores.sessions.keys()):
        if key == _POLICY_KEY or key.startswith(_INVITE_PREFIX):
            stores.sessions.pop(key, None)
    for key, value in original_policy.items():
        stores.sessions[key] = value
    for user_id in list(stores.users.keys()):
        if user_id not in original_users:
            stores.users.pop(user_id, None)


def _anonymous_client() -> TestClient:
    from main import app

    return TestClient(app)


def _register(client: TestClient, username: str, *, invite_token: str | None = None):
    body: dict[str, Any] = {
        "username": username,
        "password": "correct-horse-battery-staple",
        "confirm_password": "correct-horse-battery-staple",
    }
    if invite_token is not None:
        body["invite_token"] = invite_token
    return client.post("/v1/auth/register", json=body)


def test_missing_and_corrupt_policy_are_closed(isolated_registration_state) -> None:
    import stores
    from services.registration_policy import get_policy

    assert get_policy() == {"mode": "closed"}
    stores.sessions[_POLICY_KEY] = {"mode": "surprise"}
    assert get_policy() == {"mode": "closed"}
    stores.sessions[_POLICY_KEY] = "not-a-policy"
    assert get_policy() == {"mode": "closed"}


def test_public_registration_is_closed_by_default_after_setup(isolated_registration_state) -> None:
    client = _anonymous_client()

    status = client.get("/v1/setup/registration-policy")
    assert status.status_code == 200
    assert status.json() == {"mode": "closed"}

    response = _register(client, "blocked-user")
    assert response.status_code == 403
    assert response.json() == {"detail": "Registration is closed."}


def test_admin_can_explicitly_open_registration(isolated_registration_state, admin_client) -> None:
    response = admin_client.put(
        "/v1/settings/registration-policy",
        json={"mode": "open"},
    )
    assert response.status_code == 200
    assert response.json() == {"mode": "open"}

    registered = _register(_anonymous_client(), "explicitly-open-user")
    assert registered.status_code == 200
    assert registered.json()["user"]["username"] == "explicitly-open-user"


def test_non_admin_cannot_change_registration_policy(
    isolated_registration_state, authed_client
) -> None:
    response = authed_client.put(
        "/v1/settings/registration-policy",
        json={"mode": "open"},
    )
    assert response.status_code == 403


def test_one_time_invitation_allows_exactly_one_registration(
    isolated_registration_state, admin_client
) -> None:
    issued = admin_client.post(
        "/v1/settings/registration-invitations",
        json={"ttl_seconds": 600},
    )
    assert issued.status_code == 200
    token = issued.json()["token"]

    client = _anonymous_client()
    first = _register(client, "invited-user", invite_token=token)
    assert first.status_code == 200

    second = _register(_anonymous_client(), "replay-user", invite_token=token)
    assert second.status_code == 403


def test_failed_registration_restores_claimed_invitation(
    isolated_registration_state, admin_client
) -> None:
    issued = admin_client.post(
        "/v1/settings/registration-invitations",
        json={"ttl_seconds": 600},
    )
    token = issued.json()["token"]
    client = _anonymous_client()

    failed = client.post(
        "/v1/auth/register",
        json={
            "username": "retry-invited-user",
            "password": "correct-horse-battery-staple",
            "confirm_password": "different-password",
            "invite_token": token,
        },
    )
    assert failed.status_code == 422

    retry = _register(client, "retry-invited-user", invite_token=token)
    assert retry.status_code == 200


def test_plaintext_invitation_is_never_persisted(isolated_registration_state, admin_client) -> None:
    import stores

    issued = admin_client.post(
        "/v1/settings/registration-invitations",
        json={"ttl_seconds": 600},
    )
    token = issued.json()["token"]
    serialized = json.dumps(dict(stores.sessions.items()), default=str)
    assert token not in serialized


class TestInvitationRecordEdgeCases:
    """Direct unit coverage of the service module's own defensive branches.

    The route/middleware layer only ever sees well-formed records this
    process wrote, so these malformed and naive-timestamp shapes -- and the
    two functions (``invitation_is_valid``, ``registration_allowed``) that no
    current caller reaches -- need their own tests rather than riding along
    on an HTTP round trip that never produces them.
    """

    def test_set_policy_rejects_unsupported_mode(self) -> None:
        from services.registration_policy import set_policy

        with pytest.raises(ValueError):
            set_policy("surprise")  # type: ignore[arg-type]

    def test_create_invitation_rejects_ttl_out_of_bounds(self) -> None:
        from services.registration_policy import create_invitation

        with pytest.raises(ValueError):
            create_invitation(ttl_seconds=1)
        with pytest.raises(ValueError):
            create_invitation(ttl_seconds=8 * 24 * 60 * 60)

    def test_claim_invitation_rejects_a_non_string_expiry(
        self, isolated_registration_state
    ) -> None:
        import stores
        from services.registration_policy import _token_key, claim_invitation

        stores.sessions[_token_key("bad-token")] = {"expires_at": 12345}
        assert claim_invitation("bad-token") is None

    def test_claim_invitation_rejects_an_unparsable_expiry(
        self, isolated_registration_state
    ) -> None:
        import stores
        from services.registration_policy import _token_key, claim_invitation

        stores.sessions[_token_key("bad-token")] = {"expires_at": "not-a-timestamp"}
        assert claim_invitation("bad-token") is None

    def test_claim_invitation_accepts_a_naive_but_unexpired_timestamp(
        self, isolated_registration_state
    ) -> None:
        from datetime import datetime, timedelta

        import stores
        from services.registration_policy import _token_key, claim_invitation

        future_naive = (datetime.now() + timedelta(hours=1)).isoformat()
        stores.sessions[_token_key("naive-token")] = {"expires_at": future_naive}
        assert claim_invitation("naive-token") is not None

    def test_claim_invitation_rejects_an_expired_timestamp(
        self, isolated_registration_state
    ) -> None:
        from datetime import UTC, datetime, timedelta

        import stores
        from services.registration_policy import _token_key, claim_invitation

        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        stores.sessions[_token_key("expired-token")] = {"expires_at": past}
        assert claim_invitation("expired-token") is None

    def test_invitation_is_valid_mirrors_claim_without_consuming(
        self, isolated_registration_state
    ) -> None:
        from services.registration_policy import (
            claim_invitation,
            create_invitation,
            invitation_is_valid,
        )

        issued = create_invitation(ttl_seconds=600)
        assert invitation_is_valid(issued["token"]) is True
        assert invitation_is_valid("nonexistent") is False
        # Checking validity does not consume it -- it is still claimable after.
        assert claim_invitation(issued["token"]) is not None

    def test_restore_invitation_ignores_a_record_with_no_string_expiry(
        self, isolated_registration_state
    ) -> None:
        import stores
        from services.registration_policy import _token_key, restore_invitation

        restore_invitation("some-token", {"expires_at": 999})
        assert stores.sessions.get(_token_key("some-token")) is None

    def test_restore_invitation_ignores_an_unparsable_expiry(
        self, isolated_registration_state
    ) -> None:
        import stores
        from services.registration_policy import _token_key, restore_invitation

        restore_invitation("some-token", {"expires_at": "garbage"})
        assert stores.sessions.get(_token_key("some-token")) is None

    def test_restore_invitation_restores_a_naive_but_unexpired_record(
        self, isolated_registration_state
    ) -> None:
        from datetime import datetime, timedelta

        import stores
        from services.registration_policy import _token_key, restore_invitation

        future_naive = (datetime.now() + timedelta(hours=1)).isoformat()
        restore_invitation("some-token", {"expires_at": future_naive, "created_at": future_naive})
        assert stores.sessions.get(_token_key("some-token")) is not None

    def test_registration_allowed_checks_policy_and_invitation(
        self, isolated_registration_state
    ) -> None:
        from services.registration_policy import (
            create_invitation,
            registration_allowed,
            set_policy,
        )

        assert registration_allowed() is False
        set_policy("open")
        assert registration_allowed() is True
        set_policy("closed")
        issued = create_invitation(ttl_seconds=600)
        assert registration_allowed(issued["token"]) is True
        assert registration_allowed("bogus") is False


def test_policy_survives_store_rehydrate(monkeypatch: pytest.MonkeyPatch) -> None:
    import stores
    from services.model_store import JsonStore
    from services.registration_policy import get_policy, set_policy

    class FakePersisted:
        def __init__(self) -> None:
            self.rows: dict[tuple[str, str], str] = {}

        def put_raw(self, store_name: str, key: str, raw: str) -> None:
            self.rows[(store_name, key)] = raw

        def delete(self, store_name: str, key: str) -> None:
            self.rows.pop((store_name, key), None)

        def list_all_raw(self, store_name: str):
            return [
                (key, raw)
                for (stored_name, key), raw in self.rows.items()
                if stored_name == store_name
            ]

    persisted = FakePersisted()
    first = JsonStore("sessions", persisted)
    monkeypatch.setattr(stores, "sessions", first)
    set_policy("open")

    restarted = JsonStore("sessions", persisted)
    restarted.initialize()
    monkeypatch.setattr(stores, "sessions", restarted)
    assert get_policy() == {"mode": "open"}
