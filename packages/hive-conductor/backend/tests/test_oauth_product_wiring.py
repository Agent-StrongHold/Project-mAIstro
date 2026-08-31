"""End-to-end security tests for Hive's OIDC product wiring (SPEC-183)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import routes.auth as auth_routes
import services.oauth_login as oauth_login
import stores
from config import Settings, get_settings
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from logging_setup import OAuthCallbackQueryFilter
from main import app
from pydantic import ValidationError
from services.model_store import JsonStore
from services.oauth_login import (
    OAUTH_STATE_TTL_SECONDS,
    HiveIdentityLinkStore,
    IdentityLinkConflictError,
    OAuthLoginService,
    oauth_callback_path,
    oauth_state_cookie_name,
)

from maistro.auth.oauth import InMemoryStateStore, OAuthStateEntry
from maistro.security.auth_throttle import AuthLimits, AuthThrottle
from maistro.state import PersistedStore, State

_PROVIDER = "test"
_ISSUER = "https://idp.example.test"
_AUTHORIZATION_URL = f"{_ISSUER}/authorize"
_TOKEN_URL = f"{_ISSUER}/token"
_JWKS_URL = f"{_ISSUER}/jwks"
_USERINFO_URL = f"{_ISSUER}/userinfo"
_PUBLIC_ORIGIN = "https://conductor.example.test"
_SUCCESS_PATH = "/oauth/complete"
_CLIENT_ID = "hive-test-client"
_VAULT_KEY = "HIVE_OAUTH_TEST_CLIENT_SECRET"
_VAULT_VALUE = "sentinel-client-material"
_ACCESS_VALUE = "sentinel-access-material"
_REFRESH_VALUE = "sentinel-refresh-material"
_EMAIL_VALUE = "sentinel-person@example.test"
_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_WRONG_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key"


def _provider_document() -> dict[str, dict[str, object]]:
    return {
        _PROVIDER: {
            "authorization_url": _AUTHORIZATION_URL,
            "token_url": _TOKEN_URL,
            "client_id": _CLIENT_ID,
            "jwks_url": _JWKS_URL,
            "issuer": _ISSUER,
            "userinfo_url": _USERINFO_URL,
            "client_secret_vault_key": _VAULT_KEY,
        }
    }


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "oauth_providers": _provider_document(),
        "oauth_public_origin": _PUBLIC_ORIGIN,
        "oauth_success_path": _SUCCESS_PATH,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _b64_number(value: int) -> str:
    size = max(1, (value.bit_length() + 7) // 8)
    return base64.urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode()


def _jwks() -> dict[str, object]:
    public = _SIGNING_KEY.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": _KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64_number(public.n),
                "e": _b64_number(public.e),
            }
        ]
    }


def _id_token(
    nonce: str,
    *,
    subject: str = "subject-123",
    key: rsa.RSAPrivateKey = _SIGNING_KEY,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _CLIENT_ID,
            "sub": subject,
            "exp": now + 300,
            "iat": now,
            "nonce": nonce,
            "email": _EMAIL_VALUE,
            "email_verified": True,
        },
        key,
        algorithm="RS256",
        headers={"kid": _KID},
    )


class FakeIdentityProvider:
    def __init__(self) -> None:
        self.codes: dict[str, dict[str, object]] = {}
        self.token_forms: list[dict[str, str]] = []
        self.provider_error_detail = "sentinel-provider-error-material"

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == _JWKS_URL:
            return httpx.Response(200, json=_jwks())
        if url == _USERINFO_URL:
            return httpx.Response(200, json={"sub": "subject-123"})
        if url == _TOKEN_URL:
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            self.token_forms.append(form)
            body = self.codes.pop(form.get("code", ""), None)
            if body is None:
                return httpx.Response(
                    400,
                    json={
                        "error": "invalid_grant",
                        "error_description": self.provider_error_detail,
                    },
                )
            return httpx.Response(200, json=body)
        return httpx.Response(404)


class CountingStateStore:
    def __init__(self) -> None:
        self._delegate = InMemoryStateStore()
        self.put_count = 0

    async def put(self, state: str, entry: OAuthStateEntry) -> None:
        self.put_count += 1
        await self._delegate.put(state, entry)

    async def consume(self, state: str) -> OAuthStateEntry | None:
        return await self._delegate.consume(state)


@dataclass
class OAuthHarness:
    idp: FakeIdentityProvider
    http: httpx.AsyncClient
    links: HiveIdentityLinkStore
    service: OAuthLoginService
    secret_lookups: list[str]


def _restore_store(store: object, snapshot: dict[str, object]) -> None:
    keys = list(store.keys())  # type: ignore[attr-defined]
    for key in keys:
        store.pop(key)  # type: ignore[attr-defined]
    for key, value in snapshot.items():
        store[key] = value  # type: ignore[index]


@pytest.fixture
def oauth_harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[OAuthHarness]:
    snapshots = {
        "links": dict(stores.oauth_identity_links.items()),
        "sessions": dict(stores.sessions.items()),
        "audit": dict(stores.audit_log.items()),
        "users": dict(stores.users.items()),
    }
    stores.oauth_identity_links.clear()

    monkeypatch.setenv("OAUTH_PROVIDERS", json.dumps(_provider_document()))
    monkeypatch.setenv("OAUTH_PUBLIC_ORIGIN", _PUBLIC_ORIGIN)
    monkeypatch.setenv("OAUTH_SUCCESS_PATH", _SUCCESS_PATH)
    get_settings.cache_clear()
    monkeypatch.setattr(
        auth_routes,
        "_OAUTH_START_THROTTLE",
        AuthThrottle(auth_routes._OAUTH_START_LIMITS),
    )

    idp = FakeIdentityProvider()
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    links = HiveIdentityLinkStore()
    secret_lookups: list[str] = []

    def resolve_secret(name: str) -> str:
        secret_lookups.append(name)
        return _VAULT_VALUE

    monkeypatch.setattr(oauth_login, "resolve_secret", resolve_secret)
    harness = OAuthHarness(
        idp=idp,
        http=http,
        links=links,
        service=OAuthLoginService(get_settings(), http=http, link_store=links),
        secret_lookups=secret_lookups,
    )
    monkeypatch.setattr(auth_routes, "get_oauth_login_service", lambda: harness.service)
    yield harness

    asyncio.run(http.aclose())
    _restore_store(stores.oauth_identity_links, snapshots["links"])
    _restore_store(stores.sessions, snapshots["sessions"])
    _restore_store(stores.audit_log, snapshots["audit"])
    _restore_store(stores.users, snapshots["users"])
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(app, base_url=_PUBLIC_ORIGIN)


def _begin(client: TestClient) -> tuple[str, str, httpx.Response]:
    response = client.get(f"/v1/auth/oauth/{_PROVIDER}/start", follow_redirects=False)
    assert response.status_code == 303, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0], query["nonce"][0], response


def _queue_code(
    harness: OAuthHarness,
    code: str,
    nonce: str,
    *,
    subject: str = "subject-123",
    key: rsa.RSAPrivateKey = _SIGNING_KEY,
) -> None:
    harness.idp.codes[code] = {
        "access_token": _ACCESS_VALUE,
        "refresh_token": _REFRESH_VALUE,
        "token_type": "Bearer",
        "id_token": _id_token(nonce, subject=subject, key=key),
    }


def _callback(
    client: TestClient,
    code: str,
    state: str,
    **extra: str,
) -> httpx.Response:
    return client.get(
        f"/v1/auth/oauth/{_PROVIDER}/callback",
        params={"code": code, "state": state, **extra},
        follow_redirects=False,
    )


def _oauth_audit_entries(action: str | None = None) -> list[dict[str, Any]]:
    entries = [
        entry
        for entry in stores.audit_log.values()
        if isinstance(entry, dict) and str(entry.get("action", "")).startswith("auth.oauth.")
    ]
    if action is not None:
        return [entry for entry in entries if entry["action"] == action]
    return entries


def _assert_no_new_session(before: set[str], response: httpx.Response) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": "OAuth authentication failed"}
    assert set(stores.sessions.keys()) == before
    assert "hive_session=" not in response.headers.get("set-cookie", "")


@pytest.mark.contract("boundary")
@pytest.mark.contract("behavioral")
def test_start_callback_protected_route_happy_path(oauth_harness: OAuthHarness) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    client = _client()
    before = set(stores.sessions.keys())
    state, nonce, start = _begin(client)
    _queue_code(oauth_harness, "valid-code", nonce)

    callback = _callback(
        client,
        "valid-code",
        state,
        next="https://attacker.example.test/collect",
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == _SUCCESS_PATH
    assert callback.headers["cache-control"] == "no-store"
    assert callback.headers["referrer-policy"] == "no-referrer"
    assert callback.headers["x-frame-options"] == "DENY"
    assert callback.headers["x-content-type-options"] == "nosniff"
    assert client.get("/v1/tasks").status_code == 200
    assert oauth_harness.secret_lookups == [_VAULT_KEY]
    assert oauth_harness.idp.token_forms[-1]["client_secret"] == _VAULT_VALUE

    new_sessions = set(stores.sessions.keys()) - before
    assert len(new_sessions) == 1
    session = stores.sessions[next(iter(new_sessions))]
    serialized_session = json.dumps(session)
    for forbidden in (_ACCESS_VALUE, _REFRESH_VALUE, _EMAIL_VALUE, state, "valid-code"):
        assert forbidden not in serialized_session

    login_events = _oauth_audit_entries("auth.oauth.login")
    assert len(login_events) == 1
    assert login_events[0]["actor"] == "user"
    assert login_events[0]["detail"] == {
        "provider": _PROVIDER,
        "stage": "session",
        "reason": "success",
        "subject": "subject-123",
        "local_user_id": "user",
    }
    assert "hive_session=" in callback.headers["set-cookie"]
    assert start.headers["cache-control"] == "no-store"


def test_start_throttle_bounds_state_allocations_before_store_churn(
    oauth_harness: OAuthHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert auth_routes._OAUTH_START_LIMITS.global_failures < oauth_login.OAUTH_MAX_PENDING_STATES
    assert auth_routes._OAUTH_START_LIMITS.window_seconds == oauth_login.OAUTH_STATE_TTL_SECONDS
    states = CountingStateStore()
    oauth_harness.service = OAuthLoginService(
        get_settings(),
        http=oauth_harness.http,
        state_store=states,
        link_store=oauth_harness.links,
    )
    monkeypatch.setattr(
        auth_routes,
        "_OAUTH_START_THROTTLE",
        AuthThrottle(
            AuthLimits(
                per_client=3,
                per_account=100,
                global_failures=100,
                window_seconds=300.0,
                max_delay_seconds=0.0,
            )
        ),
    )
    client = _client()
    victim_state, _, _ = _begin(client)

    responses = [
        client.get(f"/v1/auth/oauth/{_PROVIDER}/start", follow_redirects=False) for _ in range(7)
    ]

    assert [response.status_code for response in responses] == [
        303,
        303,
        429,
        429,
        429,
        429,
        429,
    ]
    assert states.put_count == 3
    assert asyncio.run(states.consume(victim_state)) is not None
    refusal = responses[-1]
    assert refusal.headers["retry-after"] == "60"
    refusal_text = refusal.text.lower()
    assert _PROVIDER not in refusal_text
    assert _ISSUER not in refusal_text
    assert _CLIENT_ID not in refusal_text
    throttle_audits = [
        entry
        for entry in stores.audit_log.values()
        if isinstance(entry, dict) and entry.get("action") == "oauth_start_throttled"
    ]
    assert throttle_audits
    assert throttle_audits[-1]["actor"] == "oauth"
    assert throttle_audits[-1]["target"] is None
    assert throttle_audits[-1]["detail"] == {}

    for _ in range(20):
        assert (
            client.get(
                f"/v1/auth/oauth/{_PROVIDER}/start",
                follow_redirects=False,
            ).status_code
            == 429
        )
    assert states.put_count == 3


def test_state_cookie_is_short_lived_secure_and_cleared(oauth_harness: OAuthHarness) -> None:
    client = _client()
    state, _, start = _begin(client)
    cookie_name = oauth_state_cookie_name(_PROVIDER)
    set_cookie = start.headers["set-cookie"]

    assert f"{cookie_name}={state}" in set_cookie
    assert f"Max-Age={OAUTH_STATE_TTL_SECONDS}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert f"Path={oauth_callback_path(_PROVIDER)}" in set_cookie

    failure = _callback(client, "bad-code", state)
    cleared = failure.headers["set-cookie"]
    assert f"{cookie_name}=" in cleared
    assert "Max-Age=0" in cleared
    assert "HttpOnly" in cleared
    assert "Secure" in cleared
    assert "SameSite=lax" in cleared


@pytest.mark.parametrize(
    ("suffix", "method"),
    [
        ("start/", "GET"),
        ("callback/", "GET"),
        ("link", "GET"),
        ("admin", "GET"),
        ("start", "POST"),
        ("callback", "POST"),
        ("start", "HEAD"),
    ],
)
def test_only_exact_configured_oauth_get_routes_are_public(
    oauth_harness: OAuthHarness,
    suffix: str,
    method: str,
) -> None:
    response = _client().request(method, f"/v1/auth/oauth/{_PROVIDER}/{suffix}")
    assert response.status_code == 401
    if method != "HEAD":
        assert response.json()["detail"] == "Authentication required"


def test_unknown_provider_is_not_public(oauth_harness: OAuthHarness) -> None:
    response = _client().get("/v1/auth/oauth/unknown/start", follow_redirects=False)
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_configured_start_and_callback_reach_routes(oauth_harness: OAuthHarness) -> None:
    client = _client()
    assert (
        client.get(f"/v1/auth/oauth/{_PROVIDER}/start", follow_redirects=False).status_code == 303
    )
    callback = client.get(f"/v1/auth/oauth/{_PROVIDER}/callback")
    assert callback.status_code == 401
    assert callback.json()["detail"] == "OAuth authentication failed"


def test_unlinked_identity_never_provisions_a_user_or_session(
    oauth_harness: OAuthHarness,
) -> None:
    client = _client()
    state, nonce, _ = _begin(client)
    _queue_code(oauth_harness, "unlinked-code", nonce, subject="unlinked-subject")
    users_before = set(stores.users.keys())
    sessions_before = set(stores.sessions.keys())

    response = _callback(client, "unlinked-code", state)

    _assert_no_new_session(sessions_before, response)
    assert set(stores.users.keys()) == users_before
    assert _oauth_audit_entries("auth.oauth.login") == []
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["reason"] == "unlinked_identity"


def test_email_is_never_used_as_identity_join(oauth_harness: OAuthHarness) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "different-subject", "user"))
    client = _client()
    state, nonce, _ = _begin(client)
    _queue_code(oauth_harness, "same-email-code", nonce, subject="attacker-subject")
    before = set(stores.sessions.keys())

    response = _callback(client, "same-email-code", state)

    _assert_no_new_session(before, response)


def test_link_to_deleted_user_is_rejected(oauth_harness: OAuthHarness) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    stores.users.pop("user")
    client = _client()
    state, nonce, _ = _begin(client)
    _queue_code(oauth_harness, "deleted-user-code", nonce)
    before = set(stores.sessions.keys())

    response = _callback(client, "deleted-user-code", state)

    _assert_no_new_session(before, response)
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["reason"] == "unknown_user"


def test_link_to_user_disabled_after_link_is_rejected(oauth_harness: OAuthHarness) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    stores.users["user"] = stores.users["user"].model_copy(update={"is_active": False})
    client = _client()
    state, nonce, _ = _begin(client)
    _queue_code(oauth_harness, "inactive-code", nonce)
    before = set(stores.sessions.keys())

    response = _callback(client, "inactive-code", state)

    _assert_no_new_session(before, response)
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["reason"] == "inactive_user"


def test_conflicting_link_is_rejected_without_overwrite(oauth_harness: OAuthHarness) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))

    with pytest.raises(IdentityLinkConflictError, match="already linked"):
        asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "admin"))

    assert asyncio.run(oauth_harness.links.resolve(_PROVIDER, "subject-123")) == "user"


def test_new_identity_link_uses_canonical_sanitized_audit(
    oauth_harness: OAuthHarness,
) -> None:
    before = len(_oauth_audit_entries("auth.oauth.link"))

    asyncio.run(oauth_harness.links.link(_PROVIDER, "audited-subject", "user"))
    asyncio.run(oauth_harness.links.link(_PROVIDER, "audited-subject", "user"))

    entries = _oauth_audit_entries("auth.oauth.link")
    assert len(entries) == before + 1
    assert entries[-1]["actor"] == "user"
    assert entries[-1]["target"] == _PROVIDER
    assert entries[-1]["detail"] == {
        "provider": _PROVIDER,
        "stage": "identity",
        "reason": "linked",
        "subject": "audited-subject",
        "local_user_id": "user",
    }


def test_bad_code_returns_generic_401_and_no_session(oauth_harness: OAuthHarness) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    client = _client()
    state, _, _ = _begin(client)
    before = set(stores.sessions.keys())

    response = _callback(client, "provider-rejects-this-code", state)

    _assert_no_new_session(before, response)


def test_bad_signature_returns_generic_401_and_no_session(
    oauth_harness: OAuthHarness,
) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    client = _client()
    state, nonce, _ = _begin(client)
    _queue_code(oauth_harness, "bad-signature-code", nonce, key=_WRONG_SIGNING_KEY)
    before = set(stores.sessions.keys())

    response = _callback(client, "bad-signature-code", state)

    _assert_no_new_session(before, response)
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["stage"] == "token_validation"


def test_missing_id_token_cannot_use_claims_only_or_userinfo_fallback(
    oauth_harness: OAuthHarness,
) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    client = _client()
    state, _, _ = _begin(client)
    oauth_harness.idp.codes["missing-id-token-code"] = {
        "access_token": _ACCESS_VALUE,
        "token_type": "Bearer",
    }
    before = set(stores.sessions.keys())

    response = _callback(client, "missing-id-token-code", state)

    _assert_no_new_session(before, response)
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["stage"] == "token_validation"


def test_signed_id_token_without_subject_cannot_fall_back_to_userinfo(
    oauth_harness: OAuthHarness,
) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    client = _client()
    state, nonce, _ = _begin(client)
    now = int(time.time())
    id_token_without_subject = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _CLIENT_ID,
            "exp": now + 300,
            "iat": now,
            "nonce": nonce,
        },
        _SIGNING_KEY,
        algorithm="RS256",
        headers={"kid": _KID},
    )
    oauth_harness.idp.codes["missing-subject-code"] = {
        "access_token": _ACCESS_VALUE,
        "token_type": "Bearer",
        "id_token": id_token_without_subject,
    }
    before = set(stores.sessions.keys())

    response = _callback(client, "missing-subject-code", state)

    _assert_no_new_session(before, response)
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["stage"] == "token_validation"


def test_missing_client_secret_fails_closed(
    oauth_harness: OAuthHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(oauth_login, "resolve_secret", lambda _name: None)
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    client = _client()
    state, nonce, _ = _begin(client)
    _queue_code(oauth_harness, "missing-secret-code", nonce)
    before = set(stores.sessions.keys())

    response = _callback(client, "missing-secret-code", state)

    _assert_no_new_session(before, response)
    failure = _oauth_audit_entries("auth.oauth.failed")[-1]
    assert failure["detail"]["reason"] == "secret_unavailable"


@pytest.mark.parametrize(
    ("state_value", "cookie_value", "expected_stage"),
    [
        ("forged-state", "forged-state", "state"),
        ("query-state", "different-cookie-state", "browser_state"),
        ("query-state", None, "browser_state"),
    ],
)
def test_bad_or_missing_state_cookie_never_issues_session(
    oauth_harness: OAuthHarness,
    state_value: str,
    cookie_value: str | None,
    expected_stage: str,
) -> None:
    client = _client()
    headers = {}
    if cookie_value is not None:
        headers["cookie"] = f"{oauth_state_cookie_name(_PROVIDER)}={cookie_value}"
    before = set(stores.sessions.keys())
    response = client.get(
        f"/v1/auth/oauth/{_PROVIDER}/callback",
        params={"code": "unused", "state": state_value},
        headers=headers,
        follow_redirects=False,
    )

    _assert_no_new_session(before, response)
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["stage"] == expected_stage


def test_expired_state_never_issues_session(
    oauth_harness: OAuthHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    states = InMemoryStateStore(clock=lambda: now[0])
    oauth_harness.service = OAuthLoginService(
        get_settings(),
        http=oauth_harness.http,
        state_store=states,
        link_store=oauth_harness.links,
        clock=lambda: now[0],
    )
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    client = _client()
    state, nonce, _ = _begin(client)
    _queue_code(oauth_harness, "expired-code", nonce)
    now[0] += OAUTH_STATE_TTL_SECONDS + 1
    before = set(stores.sessions.keys())

    response = _callback(client, "expired-code", state)

    _assert_no_new_session(before, response)
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["stage"] == "state"


def test_state_replay_never_issues_second_session(oauth_harness: OAuthHarness) -> None:
    asyncio.run(oauth_harness.links.link(_PROVIDER, "subject-123", "user"))
    browser = _client()
    state, nonce, _ = _begin(browser)
    _queue_code(oauth_harness, "first-code", nonce)
    assert _callback(browser, "first-code", state).status_code == 303
    before = set(stores.sessions.keys())

    attacker = _client()
    replay = attacker.get(
        f"/v1/auth/oauth/{_PROVIDER}/callback",
        params={"code": "second-code", "state": state},
        headers={"cookie": f"{oauth_state_cookie_name(_PROVIDER)}={state}"},
        follow_redirects=False,
    )

    _assert_no_new_session(before, replay)
    assert _oauth_audit_entries("auth.oauth.login") != []
    assert len(_oauth_audit_entries("auth.oauth.login")) == 1


def test_provider_error_is_generic_clears_state_and_has_no_session(
    oauth_harness: OAuthHarness,
) -> None:
    client = _client()
    state, _, _ = _begin(client)
    before = set(stores.sessions.keys())
    response = client.get(
        f"/v1/auth/oauth/{_PROVIDER}/callback",
        params={
            "error": "access_denied",
            "error_description": oauth_harness.idp.provider_error_detail,
            "state": state,
        },
        follow_redirects=False,
    )

    _assert_no_new_session(before, response)
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"


def test_provider_error_consumes_state_before_clearing_cookie(
    oauth_harness: OAuthHarness,
) -> None:
    browser = _client()
    state, _, _ = _begin(browser)
    first = browser.get(
        f"/v1/auth/oauth/{_PROVIDER}/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )
    assert first.status_code == 401
    before = set(stores.sessions.keys())

    replay = _client().get(
        f"/v1/auth/oauth/{_PROVIDER}/callback",
        params={"code": "unused", "state": state},
        headers={"cookie": f"{oauth_state_cookie_name(_PROVIDER)}={state}"},
        follow_redirects=False,
    )

    _assert_no_new_session(before, replay)
    assert _oauth_audit_entries("auth.oauth.failed")[-1]["detail"]["stage"] == "state"


@pytest.mark.parametrize("duplicate", ["code", "state"])
def test_duplicate_callback_parameters_fail_closed(
    oauth_harness: OAuthHarness,
    duplicate: str,
) -> None:
    client = _client()
    state, _, _ = _begin(client)
    params: list[tuple[str, str]] = [("code", "first"), ("state", state)]
    params.append((duplicate, "second"))
    before = set(stores.sessions.keys())

    response = client.get(
        f"/v1/auth/oauth/{_PROVIDER}/callback",
        params=params,
        follow_redirects=False,
    )

    _assert_no_new_session(before, response)


def test_callback_query_values_are_absent_from_request_logs(
    oauth_harness: OAuthHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _client()
    state, _, _ = _begin(client)
    callback_code = "sentinel-callback-code-material"
    caplog.set_level(logging.DEBUG, logger="hive.request")

    _callback(client, callback_code, state)

    request_logs = "\n".join(
        record.getMessage() for record in caplog.records if record.name == "hive.request"
    )
    assert callback_code not in request_logs
    assert state not in request_logs
    assert "session_cookie=present" not in request_logs


def test_uvicorn_access_log_filter_removes_entire_callback_query() -> None:
    assert any(
        isinstance(item, OAuthCallbackQueryFilter)
        for item in logging.getLogger("uvicorn.access").filters
    )
    callback_code = "sentinel-uvicorn-code-material"
    callback_state = "sentinel-uvicorn-state-material"
    path = (
        f"/v1/auth/oauth/{_PROVIDER}/callback"
        f"?code={callback_code}&state={callback_state}&other=public"
    )
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", "GET", path, "1.1", 303),
        exc_info=None,
    )

    assert OAuthCallbackQueryFilter().filter(record) is True
    rendered = record.getMessage()
    assert callback_code not in rendered
    assert callback_state not in rendered
    assert "other=public" not in rendered
    assert f"/v1/auth/oauth/{_PROVIDER}/callback HTTP/1.1" in rendered


def test_failure_audit_contains_only_normalized_non_secret_fields(
    oauth_harness: OAuthHarness,
) -> None:
    client = _client()
    state, _, _ = _begin(client)
    callback_code = "sentinel-audit-code-material"
    _callback(client, callback_code, state)

    entries = _oauth_audit_entries("auth.oauth.failed")
    serialized = json.dumps(entries)
    for forbidden in (
        callback_code,
        state,
        _VAULT_VALUE,
        _ACCESS_VALUE,
        _REFRESH_VALUE,
        _EMAIL_VALUE,
        oauth_harness.idp.provider_error_detail,
    ):
        assert forbidden not in serialized
    assert set(entries[-1]["detail"]) == {"provider", "stage", "reason"}


def test_identity_link_survives_durable_restart(
    oauth_harness: OAuthHarness,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "oauth-state.db"
    first_state = State(db_path)
    first_persisted = PersistedStore(first_state)
    first_persisted.initialize()
    first_json = JsonStore("oauth_identity_links", first_persisted)
    first_links = HiveIdentityLinkStore(first_json)
    stale_json = JsonStore("oauth_identity_links", first_persisted)
    stale_json.initialize()
    stale_links = HiveIdentityLinkStore(stale_json)
    asyncio.run(first_links.link(_PROVIDER, "durable-subject", "user"))
    with pytest.raises(IdentityLinkConflictError):
        asyncio.run(stale_links.link(_PROVIDER, "durable-subject", "admin"))
    assert asyncio.run(stale_links.resolve(_PROVIDER, "durable-subject")) == "user"
    first_state.flush()
    first_state.close()

    second_state = State(db_path)
    second_persisted = PersistedStore(second_state)
    second_persisted.initialize()
    second_json = JsonStore("oauth_identity_links", second_persisted)
    second_json.initialize()
    second_links = HiveIdentityLinkStore(second_json)
    try:
        assert asyncio.run(second_links.resolve(_PROVIDER, "durable-subject")) == "user"
        with pytest.raises(IdentityLinkConflictError):
            asyncio.run(second_links.link(_PROVIDER, "durable-subject", "admin"))
        assert asyncio.run(second_links.resolve(_PROVIDER, "durable-subject")) == "user"
    finally:
        second_state.close()


def test_abandoned_starts_are_bounded_in_backend_runtime() -> None:
    states = InMemoryStateStore(max_entries=2)

    async def put_states() -> tuple[OAuthStateEntry | None, OAuthStateEntry | None]:
        for index in range(3):
            await states.put(
                f"state-{index}",
                OAuthStateEntry(
                    provider=_PROVIDER,
                    code_verifier="v" * 43,
                    redirect_uri=f"{_PUBLIC_ORIGIN}{oauth_callback_path(_PROVIDER)}",
                    nonce="nonce",
                    expires_at=time.monotonic() + 60 + index,
                ),
            )
        return await states.consume("state-0"), await states.consume("state-2")

    oldest, newest = asyncio.run(put_states())
    assert oldest is None
    assert newest is not None


def test_oauth_config_is_typed_non_secret_and_fixed() -> None:
    settings = _settings()
    provider = settings.oauth_providers[_PROVIDER]

    assert not hasattr(provider, "client_secret")
    assert provider.client_secret_vault_key == _VAULT_KEY
    assert settings.oauth_success_path == _SUCCESS_PATH
    assert settings.oauth_public_origin == _PUBLIC_ORIGIN


@pytest.mark.parametrize(
    "overrides",
    [
        {"oauth_public_origin": None},
        {"oauth_success_path": "https://attacker.example.test/collect"},
        {"oauth_success_path": "//attacker.example.test/collect"},
        {
            "oauth_providers": {
                _PROVIDER: {
                    **_provider_document()[_PROVIDER],
                    "token_url": "http://idp.example.test/token",
                }
            }
        },
        {
            "oauth_providers": {
                _PROVIDER: {
                    **_provider_document()[_PROVIDER],
                    "client_secret": "must-not-be-a-config-field",
                }
            }
        },
        {
            "oauth_providers": {
                _PROVIDER: {
                    **_provider_document()[_PROVIDER],
                    "authorization_url": (
                        "https://idp.example.test/authorize\r\nX-Injected: value"
                    ),
                }
            }
        },
        {"oauth_providers": {"Not-A-Provider": _provider_document()[_PROVIDER]}},
    ],
)
def test_oauth_config_rejects_insecure_or_secret_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)


def test_rejected_config_secret_is_not_echoed_in_validation_error() -> None:
    secret_value = "sentinel-rejected-config-material"
    provider = {
        **_provider_document()[_PROVIDER],
        "client_secret": secret_value,
    }

    with pytest.raises(ValidationError) as raised:
        _settings(oauth_providers={_PROVIDER: provider})

    assert secret_value not in str(raised.value)
