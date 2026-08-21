"""Session invalidation — remediation for the disclosure in #281 / #332.

An attacker who read the session store holds valid session ids; the only fix
is to revoke every session so each one stops resolving to a user.
"""

from __future__ import annotations

import pathlib
import sys
from collections.abc import Iterator
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture()
def preserved_sessions() -> Iterator[None]:
    """Purging is global; hand the session-scoped fixtures their logins back."""
    import stores

    snapshot = dict(stores.sessions.items())
    try:
        yield
    finally:
        stores.sessions.clear()
        for key, value in snapshot.items():
            stores.sessions[key] = value


def _login() -> tuple[Any, str]:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200
    session_id = client.cookies.get("hive_session")
    assert session_id
    return client, session_id


def test_purge_revokes_a_live_session(preserved_sessions: None) -> None:
    import stores

    client, session_id = _login()
    assert client.get("/v1/auth/whoami").json()["authenticated"] is True
    assert session_id in stores.sessions

    revoked = stores.purge_all_sessions()

    assert revoked >= 1
    assert len(stores.sessions) == 0
    assert session_id not in stores.sessions
    # The cookie the client still holds no longer resolves to a user.
    assert client.get("/v1/auth/whoami").json()["authenticated"] is False


def test_purge_empties_the_store(preserved_sessions: None) -> None:
    import stores

    _login()
    _login()
    assert len(stores.sessions) >= 2

    stores.purge_all_sessions()

    assert len(stores.sessions) == 0
    assert list(stores.sessions.keys()) == []


def test_purge_on_empty_store_is_a_noop(preserved_sessions: None) -> None:
    import stores

    stores.purge_all_sessions()
    assert stores.purge_all_sessions() == 0


def test_login_still_works_after_a_purge(preserved_sessions: None) -> None:
    import stores

    _login()
    stores.purge_all_sessions()

    client, session_id = _login()
    assert session_id in stores.sessions
    assert client.get("/v1/auth/whoami").json()["authenticated"] is True


def test_json_store_clear_deletes_from_persistence() -> None:
    """clear() must route through the same per-key delete as pop()."""
    from services.model_store import JsonStore

    class _FakePersisted:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, str]] = []

        def put_raw(self, store_name: str, key: str, raw: str) -> None:
            return None

        def delete(self, store_name: str, key: str) -> None:
            self.deleted.append((store_name, key))

    persisted = _FakePersisted()
    store = JsonStore("sessions", persisted)
    store["s1"] = {"user_id": "u1"}
    store["s2"] = {"user_id": "u2"}

    assert store.clear() == 2

    assert len(store) == 0
    assert sorted(persisted.deleted) == [("sessions", "s1"), ("sessions", "s2")]
    assert store.clear() == 0
