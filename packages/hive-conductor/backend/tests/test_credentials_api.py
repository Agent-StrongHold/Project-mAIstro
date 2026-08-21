"""Credentials API — per-user encrypted storage."""

from __future__ import annotations

from fastapi.testclient import TestClient
from main import app


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
    alice = TestClient(app)
    reg = alice.post(
        "/v1/auth/register",
        json={
            "username": "credalice",
            "password": "securepass1",
            "confirm_password": "securepass1",
        },
    )
    assert reg.status_code == 200, reg.text
    alice.put("/v1/credentials/jira", json={"secret": "alice-only-token"})

    bob = TestClient(app)
    bob.post(
        "/v1/auth/register",
        json={
            "username": "credbob",
            "password": "securepass1",
            "confirm_password": "securepass1",
        },
    )
    bob_list = bob.get("/v1/credentials")
    jira_row = next(r for r in bob_list.json()["credentials"] if r["id"] == "jira")
    assert jira_row["configured"] is False
