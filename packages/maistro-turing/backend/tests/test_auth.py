from __future__ import annotations


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unauthenticated_v1_rejected(client):
    r = client.get("/v1/state/snapshot")
    assert r.status_code == 401


def test_login_and_whoami(authed_client):
    r = authed_client.get("/v1/auth/whoami")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["role"] == "user"


def test_bad_credentials(client):
    r = client.post("/v1/auth/login", json={"username": "testuser", "password": "wrong"})
    assert r.status_code == 401


def test_service_key_authenticates(turing_service_client):
    # Service key is not a human session, so whoami reports unauthenticated user
    # but the request itself is not 401 (it carries a valid service identity).
    r = turing_service_client.get("/v1/auth/whoami")
    assert r.status_code == 200
    assert r.json()["authenticated"] is False
