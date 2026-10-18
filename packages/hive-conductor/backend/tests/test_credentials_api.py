"""Credentials API — per-user encrypted storage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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

    import httpx

    monkeypatch.setattr(
        "routes.credentials.sync_client",
        lambda **_kwargs: (_ for _ in ()).throw(httpx.ConnectError("certificate verify failed")),
    )
    response = c.post(
        "/v1/credentials/openai_compatible/test",
        json={"config": config, "secret": "draft-key"},
    )
    assert response.status_code == 502
    assert "TLS" in response.json()["detail"]


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
    for base_url in (
        "https://gateway.example/v1?",
        "https://gateway.example/v1#",
        "https://gateway.example\\v1",
    ):
        rejected = c.put(
            "/v1/credentials/openai_compatible/config",
            json={"config": {"display_name": "bad", "base_url": base_url}},
        )
        assert rejected.status_code == 422

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


def _closed_loopback_port() -> int:
    """A loopback port with nothing listening on it (connection refused)."""

    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_openai_compatible_probe_over_real_transport() -> None:
    """Discovery and failure classification through the real guarded transport.

    The other probe tests stub `routes.credentials.sync_client`, which proves
    the route's classification logic but not the seam it documents: the probe
    must actually leave through `maistro.http.sync_client`, reach a loopback
    origin only because saving the config registered that exact origin with
    the outbound policy (#67), classify a refused connection as
    `connectivity`, and refuse a redirect hop to a destination the policy
    never allowed. A loopback HTTP server exercises all three without any
    external dependency.
    """

    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/redirect-test/"):
                # 302 to a private address no test ever registered. The saved
                # origin is allowed; the redirect target is not, and the
                # transport must refuse the hop rather than follow it (#67).
                self.send_response(302)
                self.send_header("Location", "http://10.203.0.7/v1/models")
                self.end_headers()
            elif self.path.endswith("/models"):
                payload = json.dumps({"data": [{"id": "loopback-model"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_args: object) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        c = _login()
        saved = c.put(
            "/v1/credentials/openai_compatible/config",
            json={
                "config": {
                    "display_name": "Loopback",
                    "base_url": f"http://127.0.0.1:{port}/v1",
                }
            },
        )
        assert saved.status_code == 200, saved.text

        found = c.post("/v1/credentials/openai_compatible/test", json={"secret": "loopback-key"})
        assert found.status_code == 200, found.text
        assert found.json()["models"] == ["loopback-model"]

        refused = c.post(
            "/v1/credentials/openai_compatible/test",
            json={
                "config": {"base_url": f"http://127.0.0.1:{_closed_loopback_port()}/v1"},
                "secret": "loopback-key",
            },
        )
        assert refused.status_code == 502
        assert refused.json()["detail"].startswith("connectivity:"), refused.text

        redirected = c.post(
            "/v1/credentials/openai_compatible/test",
            json={
                "config": {"base_url": f"http://127.0.0.1:{port}/redirect-test"},
                "secret": "loopback-key",
            },
        )
        assert redirected.status_code == 422
        assert "policy rejection" in redirected.json()["detail"], redirected.text
    finally:
        server.shutdown()


def test_openai_compatible_delete_removes_config_without_a_secret() -> None:
    c = _login()
    saved = c.put(
        "/v1/credentials/openai_compatible/config",
        json={
            "config": {
                "display_name": "Draft gateway",
                "base_url": "https://gateway.example/v1",
            }
        },
    )
    assert saved.status_code == 200, saved.text
    deleted = c.delete("/v1/credentials/openai_compatible")
    assert deleted.status_code == 204, deleted.text
    assert c.get("/v1/credentials/openai_compatible/config").json()["config"] == {}


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

    # Inspect the canonical store only inside the test to prove Bob's guessed
    # provider id did not rotate Alice's ciphertext.
    from services.user_credentials import require_store

    assert (
        require_store().use_secret("cred-scope-alice", "jira", lambda secret: secret)
        == "alice-only-token"
    )
