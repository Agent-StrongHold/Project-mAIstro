"""Credentials API — per-user encrypted storage."""

from __future__ import annotations

from typing import Any

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


def test_openai_compatible_probe_requires_credential_write() -> None:
    c = _login("testuser", "testpass")
    response = c.post(
        "/v1/credentials/openai_compatible/test",
        json={"config": {"display_name": "probe", "base_url": "http://127.0.0.1:9"}},
    )
    assert response.status_code == 403


def test_openai_compatible_probe_classifies_failures(monkeypatch) -> None:
    c = _login()
    config = {"display_name": "Gateway", "base_url": "http://gateway.internal/v1"}
    assert (
        c.put("/v1/credentials/openai_compatible/config", json={"config": config}).status_code
        == 200
    )

    class _Response:
        def __init__(self, status_code: int, payload: object) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> object:
            return self._payload

    class _Client:
        def __init__(self, response: _Response) -> None:
            self.response = response

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, _url: str, *, headers: dict[str, str]) -> _Response:
            del headers
            return self.response

    for status_code, payload, category in (
        (401, {"error": "nope"}, "authentication"),
        (200, {"models": []}, "incompatible API behavior"),
    ):
        monkeypatch.setattr(
            "routes.credentials.sync_client",
            lambda _status_code=status_code, _payload=payload, **_kwargs: _Client(
                _Response(_status_code, _payload)
            ),
        )
        response = c.post(
            "/v1/credentials/openai_compatible/test",
            json={"config": config, "secret": "draft-key"},
        )
        assert category in response.json()["detail"]

    from maistro.security.ssrf import SSRFBlockedError

    def _blocked(**_kwargs: object) -> None:
        raise SSRFBlockedError("redirect blocked", reason="internal_address")

    monkeypatch.setattr("routes.credentials.sync_client", _blocked)
    response = c.post(
        "/v1/credentials/openai_compatible/test",
        json={"config": config, "secret": "draft-key"},
    )
    assert response.status_code == 422
    assert "policy rejection" in response.json()["detail"]


def test_openai_compatible_credential_lifecycle_and_non_persisting_test(
    monkeypatch,
) -> None:
    """The generic gateway uses the vault path and supports safe lifecycle edits."""
    c = _login()
    provider = next(
        row
        for row in c.get("/v1/credentials").json()["credentials"]
        if row["id"] == "openai_compatible"
    )
    assert {field["name"] for field in provider["config_fields"]} == {
        "display_name",
        "base_url",
        "organization",
        "project",
    }

    before_invalid_test = c.get("/v1/credentials/openai_compatible/config").json()["config"]
    invalid = c.post(
        "/v1/credentials/openai_compatible/test",
        json={
            "config": {"display_name": "bad", "base_url": "file:///etc/passwd"},
            "secret": "not-persisted",
        },
    )
    assert invalid.status_code == 422
    assert c.get("/v1/credentials/openai_compatible/config").json()["config"] == before_invalid_test

    config = {
        "display_name": "Private gateway",
        "base_url": "http://gateway.internal/v1",
        "organization": "org-acme",
        "project": "proj-pm",
    }
    assert (
        c.put("/v1/credentials/openai_compatible/config", json={"config": config}).status_code
        == 200
    )

    seen_headers: list[dict[str, str]] = []

    class _Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"data": [{"id": "private-model"}, {"id": "fast-model"}]}

    class _Client:
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, _url: str, *, headers: dict[str, str]) -> _Response:
            seen_headers.append(headers)
            return _Response()

    monkeypatch.setattr("routes.credentials.sync_client", lambda **_kwargs: _Client())

    first_test = c.post(
        "/v1/credentials/openai_compatible/test",
        json={"config": config, "secret": "first-key"},
    )
    assert first_test.status_code == 200, first_test.text
    assert first_test.json()["models"] == ["fast-model", "private-model"]
    assert first_test.json()["binding"]["capability"] == "model.chat"
    assert first_test.json()["binding"]["credential_refs"] == ["openai_compatible"]
    assert "first-key" not in first_test.text
    assert seen_headers[-1]["OpenAI-Organization"] == "org-acme"
    assert seen_headers[-1]["OpenAI-Project"] == "proj-pm"

    assert (
        c.put("/v1/credentials/openai_compatible", json={"secret": "first-key"}).status_code == 200
    )
    # Editing endpoint metadata does not replace the key: an omitted test key
    # is resolved inside use_secret and never enters the response.
    edited = {**config, "display_name": "Edited gateway"}
    assert (
        c.put("/v1/credentials/openai_compatible/config", json={"config": edited}).status_code
        == 200
    )
    existing_key_test = c.post("/v1/credentials/openai_compatible/test", json={"config": edited})
    assert existing_key_test.status_code == 200, existing_key_test.text
    assert seen_headers[-1]["Authorization"] == "Bearer first-key"

    assert (
        c.put("/v1/credentials/openai_compatible", json={"secret": "rotated-key"}).status_code
        == 200
    )
    assert (
        c.put("/v1/credentials/openai_compatible/config", json={"enabled": False}).status_code
        == 200
    )
    listing = c.get("/v1/credentials").json()["credentials"]
    generic = next(row for row in listing if row["id"] == "openai_compatible")
    assert generic["configured"] is True
    assert generic["enabled"] is False
    assert c.delete("/v1/credentials/openai_compatible").status_code == 204
    deleted = c.get("/v1/credentials/openai_compatible/config").json()
    assert deleted["config"] == {}


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
