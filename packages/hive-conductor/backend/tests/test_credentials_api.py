"""Credentials API — per-user encrypted storage."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from main import app


def _credential_writer(user_id: str) -> TestClient:
    """Return a distinct principal cleared for credential CRUD."""
    import stores

    from maistro.security.passwords import hash_password

    stores.users[user_id] = stores.users._model_class(
        id=user_id,
        username=user_id,
        password_hash=hash_password("credential-pass"),
        role="user",
        is_active=True,
        permissions=["credentials.write"],
        created_at=datetime.now(UTC),
    )
    client = TestClient(app)
    login = client.post(
        "/v1/auth/login",
        json={"username": user_id, "password": "credential-pass"},
    )
    assert login.status_code == 200, login.text
    elevated = client.post(
        "/v1/auth/elevate",
        json={
            "password": "credential-pass",
            "permissions": ["credentials.write"],
            "task_id": f"credential-scope-{user_id}",
        },
    )
    assert elevated.status_code == 200, elevated.text
    return client


def _login(username: str = "testadmin", password: str = "adminpass") -> TestClient:
    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


def test_save_and_list_credentials() -> None:
    c = _login()
    save = c.put("/v1/credentials/jira", json={"secret": "atlassian-token-123"})
    assert save.status_code == 200, save.text

    listing = c.get("/v1/credentials")
    assert listing.status_code == 200
    rows = {row["id"]: row for row in listing.json()["credentials"]}
    assert rows["jira"]["configured"] is True
    assert "atlassian-token" not in str(listing.json())


def test_credentials_list_surfaces_config_fields_for_airtable() -> None:
    """task #27 — providers with config_fields surface them on /v1/credentials.
    Airtable has base_id + table; jira has jql + site_url."""
    c = _login()
    listing = c.get("/v1/credentials")
    assert listing.status_code == 200
    rows = {r["id"]: r for r in listing.json()["credentials"]}

    airtable = rows["airtable"]
    field_names = {f["name"] for f in airtable["config_fields"]}
    assert "base_id" in field_names
    assert "table" in field_names
    required_for_base = next(f for f in airtable["config_fields"] if f["name"] == "base_id")[
        "required"
    ]
    assert required_for_base is True
    # config_values starts empty
    assert airtable["config_values"] == {}

    # Jira has 2 config fields: jql + site_url
    jira_field_names = {f["name"] for f in rows["jira"]["config_fields"]}
    assert jira_field_names == {"jql", "site_url"}


def test_credentials_config_put_and_get_round_trips() -> None:
    """task #27 — PUT /v1/credentials/airtable/config persists; GET returns it."""
    c = _login()
    save = c.put(
        "/v1/credentials/airtable/config",
        json={"config": {"base_id": "appABC123", "table": "Initiatives"}},
    )
    assert save.status_code == 200
    assert save.json()["config"] == {
        "base_id": "appABC123",
        "table": "Initiatives",
    }

    read = c.get("/v1/credentials/airtable/config")
    assert read.status_code == 200
    assert read.json()["config"] == {
        "base_id": "appABC123",
        "table": "Initiatives",
    }


def test_credentials_config_rejects_unknown_field() -> None:
    c = _login()
    r = c.put(
        "/v1/credentials/airtable/config",
        json={"config": {"hacker_field": "value", "base_id": "appX"}},
    )
    assert r.status_code == 400
    assert "hacker_field" in r.json()["detail"]


def test_credentials_config_rejects_oversize_value() -> None:
    c = _login()
    r = c.put(
        "/v1/credentials/airtable/config",
        json={"config": {"base_id": "x" * 257}},
    )
    assert r.status_code == 400


def test_credentials_config_unknown_provider_404() -> None:
    c = _login()
    r = c.put(
        "/v1/credentials/no-such-provider/config",
        json={"config": {}},
    )
    assert r.status_code == 404
    r2 = c.get("/v1/credentials/no-such-provider/config")
    assert r2.status_code == 404


def test_user_cannot_see_other_users_secrets() -> None:
    alice = _credential_writer("cred-scope-alice")
    alice_save = alice.put("/v1/credentials/jira", json={"secret": "alice-only-token"})
    assert alice_save.status_code == 200

    bob = _credential_writer("cred-scope-bob")
    bob_list = bob.get("/v1/credentials")
    assert bob_list.status_code == 200
    jira_row = next(r for r in bob_list.json()["credentials"] if r["id"] == "jira")
    assert jira_row["configured"] is False

    # Guessing the shared provider id must not let Bob rotate or delete
    # Alice's record; both operations apply only to Bob's principal scope.
    assert bob.put("/v1/credentials/jira", json={"secret": "bob-token"}).status_code == 200
    assert bob.delete("/v1/credentials/jira").status_code == 204

    alice_after = alice.get("/v1/credentials")
    assert alice_after.status_code == 200
    alice_jira = next(r for r in alice_after.json()["credentials"] if r["id"] == "jira")
    assert alice_jira["configured"] is True
