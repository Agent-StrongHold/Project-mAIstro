"""What the Conductor actually stores for a password, on the real HTTP path.

`maistro.security.passwords` has direct unit coverage for hash/verify/rehash.
What had no coverage was the product claim built on top of it: that registration
stores Argon2id, and that a legacy bcrypt row is upgraded the first time its
owner logs in. `conftest._seed_test_user` even asserts the upgrade in a comment
("login auto-upgrades to Argon2id on success") while nothing checked it — the
exact shape of claim that outlives the code it describes.

These tests seed their own rows rather than using the shared fixtures: the
session-scoped `authed_client` logs in during setup, so the seeded users have
already been upgraded by the time any test body runs, and asserting on them
would pass whether or not the upgrade path still exists.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

# bcrypt hash of "testpass" — the legacy format registration no longer produces.
_LEGACY_BCRYPT = "$2b$12$hmpbR.C6bkLEJ4d9PYzoqOthlZNKk.WOSjXnLxHpC0Y3S6sgdYfPq"
_LEGACY_PASSWORD = "testpass"


@pytest.fixture
def client() -> TestClient:
    from main import app

    return TestClient(app)


@pytest.fixture
def seeded():
    """Seed users by id, and remove exactly what was seeded afterwards."""
    import stores

    created: list[str] = []

    def _seed(user_id: str, username: str, password_hash: str) -> None:
        stores.users[user_id] = stores.users._model_class(
            id=user_id,
            username=username,
            password_hash=password_hash,
            role="user",
            is_active=True,
            permissions=[],
            created_at=datetime.now(UTC),
        )
        created.append(user_id)

    yield _seed

    for user_id in created:
        stores.users.pop(user_id, None)


def _stored_hash(username: str) -> str:
    import stores

    for user in stores.users.values():
        if user.username == username:
            return str(user.password_hash)
    raise AssertionError(f"no user named {username!r}")


def test_registration_stores_argon2id_and_never_the_password(client) -> None:
    import stores

    username = "argon2-registrant"
    response = client.post(
        "/v1/auth/register",
        json={
            "username": username,
            "password": "a-sufficiently-long-password",
            "confirm_password": "a-sufficiently-long-password",
        },
    )
    assert response.status_code == 200, response.text
    try:
        stored = _stored_hash(username)
        assert stored.startswith("$argon2id$")
        assert "a-sufficiently-long-password" not in stored
    finally:
        for user_id, user in list(stores.users.items()):
            if user.username == username:
                stores.users.pop(user_id, None)


def test_login_upgrades_a_legacy_bcrypt_row_to_argon2id(client, seeded) -> None:
    seeded("legacy-upgrade", "legacyuser", _LEGACY_BCRYPT)
    assert _stored_hash("legacyuser").startswith("$2b$")

    response = client.post(
        "/v1/auth/login",
        json={"username": "legacyuser", "password": _LEGACY_PASSWORD},
    )
    assert response.status_code == 200, response.text

    upgraded = _stored_hash("legacyuser")
    assert upgraded.startswith("$argon2id$")
    assert upgraded != _LEGACY_BCRYPT

    # The upgrade must not have changed what the password is: a rehash that
    # locked the owner out would be worse than leaving bcrypt in place.
    again = client.post(
        "/v1/auth/login",
        json={"username": "legacyuser", "password": _LEGACY_PASSWORD},
    )
    assert again.status_code == 200
    assert _stored_hash("legacyuser") == upgraded


def test_a_failed_login_never_rewrites_the_stored_hash(client, seeded) -> None:
    seeded("legacy-wrongpw", "legacywrong", _LEGACY_BCRYPT)

    response = client.post(
        "/v1/auth/login",
        json={"username": "legacywrong", "password": "not-the-password"},
    )
    assert response.status_code == 401
    assert _stored_hash("legacywrong") == _LEGACY_BCRYPT


@pytest.mark.parametrize(
    "corrupt",
    [
        "plaintext-not-a-hash",
        "$2b$not-a-valid-bcrypt-hash",
        "$argon2id$garbage",
        "",
    ],
)
def test_an_unreadable_stored_hash_fails_closed(client, seeded, corrupt: str) -> None:
    """A row whose hash cannot be parsed must deny, not admit. Failing open here
    would turn a corrupt database column into an authentication bypass."""
    seeded("corrupt-hash", "corruptuser", corrupt)

    response = client.post(
        "/v1/auth/login",
        json={"username": "corruptuser", "password": _LEGACY_PASSWORD},
    )
    assert response.status_code == 401
    assert _stored_hash("corruptuser") == corrupt
