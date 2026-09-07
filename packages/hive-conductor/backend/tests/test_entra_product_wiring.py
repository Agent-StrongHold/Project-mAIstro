"""Entra tenant-bound login and the explicit login mode, through real wiring.

`maistro-core`'s `tests/auth/test_entra.py` proves the Entra identity semantics
in isolation. These tests prove they are *reached*: real settings build the
provider, the service dispatches verification by provider, the durable link
carries the immutable ``tid:oid`` pair rather than a pairwise subject, and the
login route consults the deployment's explicit mode policy instead of inferring
availability from configured providers (#491). A correct policy nothing calls
is the shape #257 was filed about.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx
import jwt as pyjwt
import pytest
import routes.auth as auth_routes
import stores
from config import OAuthProviderSettings, Settings, get_settings
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from main import app
from pydantic import ValidationError
from services.oauth_login import (
    HiveIdentityLinkStore,
    OAuthLoginService,
    _identity_link_key,
)

from maistro.security.auth_throttle import AuthThrottle

_ENTRA_TENANT = "11111111-2222-3333-4444-555555555555"
_ENTRA_TENANT_BASE = f"https://login.microsoftonline.com/{_ENTRA_TENANT}"
_ENTRA_AUTHORIZATION_URL = f"{_ENTRA_TENANT_BASE}/oauth2/v2.0/authorize"
_ENTRA_TOKEN_URL = f"{_ENTRA_TENANT_BASE}/oauth2/v2.0/token"
_ENTRA_JWKS_URL = f"{_ENTRA_TENANT_BASE}/discovery/v2.0/keys"
_ENTRA_ISSUER = f"{_ENTRA_TENANT_BASE}/v2.0"
_ENTRA_CLIENT_ID = "hive-entra-client"
_ENTRA_TID = _ENTRA_TENANT
_ENTRA_OID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_ENTRA_SUBJECT = f"{_ENTRA_TID}:{_ENTRA_OID}"
_PAIRWISE_SUB = "pairwise-sub-never-linked"
_OTHER_TENANT = "99999999-8888-7777-6666-555555555555"

_GENERIC_PROVIDER = "generic"
_GENERIC_ISSUER = "https://idp.example.test"
_GENERIC_AUTHORIZATION_URL = f"{_GENERIC_ISSUER}/authorize"
_GENERIC_TOKEN_URL = f"{_GENERIC_ISSUER}/token"
_GENERIC_JWKS_URL = f"{_GENERIC_ISSUER}/jwks"
_GENERIC_CLIENT_ID = "hive-generic-client"
_GENERIC_SUB = "generic-subject-123"

_PUBLIC_ORIGIN = "https://conductor.example.test"
_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "entra-test-key"


def _entra_provider_document() -> dict[str, dict[str, object]]:
    return {
        "entra": {
            "client_id": _ENTRA_CLIENT_ID,
            "entra_tenant_id": _ENTRA_TENANT,
        }
    }


def _hybrid_provider_document() -> dict[str, dict[str, object]]:
    return {
        **_entra_provider_document(),
        _GENERIC_PROVIDER: {
            "authorization_url": _GENERIC_AUTHORIZATION_URL,
            "token_url": _GENERIC_TOKEN_URL,
            "client_id": _GENERIC_CLIENT_ID,
            "jwks_url": _GENERIC_JWKS_URL,
            "issuer": _GENERIC_ISSUER,
        },
    }


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
    issuer: str,
    audience: str,
    subject: str,
    extra_claims: dict[str, str],
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "exp": now + 300,
        "iat": now,
        "nonce": nonce,
    }
    claims.update(extra_claims)
    return pyjwt.encode(claims, _SIGNING_KEY, algorithm="RS256", headers={"kid": _KID})


def _entra_id_token(nonce: str, *, tid: str = _ENTRA_TID) -> str:
    return _id_token(
        nonce,
        issuer=_ENTRA_ISSUER,
        audience=_ENTRA_CLIENT_ID,
        subject=_PAIRWISE_SUB,
        extra_claims={"tid": tid, "oid": _ENTRA_OID},
    )


class FakeIdentityProvider:
    """Serve the tenant-specific Entra v2 endpoints (and one generic IdP)."""

    def __init__(self) -> None:
        self.codes: dict[str, dict[str, object]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in (_ENTRA_JWKS_URL, _GENERIC_JWKS_URL):
            return httpx.Response(200, json=_jwks())
        if url in (_ENTRA_TOKEN_URL, _GENERIC_TOKEN_URL):
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            body = self.codes.pop(form.get("code", ""), None)
            if body is None:
                return httpx.Response(
                    400, json={"error": "invalid_grant", "error_description": "unknown code"}
                )
            return httpx.Response(200, json=body)
        return httpx.Response(404)


@dataclass
class EntraHarness:
    idp: FakeIdentityProvider
    http: httpx.AsyncClient
    links: HiveIdentityLinkStore
    service: OAuthLoginService


def _restore_store(store: object, snapshot: dict[str, object]) -> None:
    keys = list(store.keys())  # type: ignore[attr-defined]
    for key in keys:
        store.pop(key)  # type: ignore[attr-defined]
    for key, value in snapshot.items():
        store[key] = value  # type: ignore[index]


def _make_harness(
    monkeypatch: pytest.MonkeyPatch,
    providers: dict[str, dict[str, object]],
) -> EntraHarness:
    snapshots = {
        "links": dict(stores.oauth_identity_links.items()),
        "sessions": dict(stores.sessions.items()),
        "audit": dict(stores.audit_log.items()),
        "users": dict(stores.users.items()),
    }
    stores.oauth_identity_links.clear()

    monkeypatch.setenv("OAUTH_PROVIDERS", json.dumps(providers))
    monkeypatch.setenv("OAUTH_PUBLIC_ORIGIN", _PUBLIC_ORIGIN)
    get_settings.cache_clear()
    monkeypatch.setattr(
        auth_routes,
        "_OAUTH_START_THROTTLE",
        AuthThrottle(auth_routes._OAUTH_START_LIMITS),
    )
    monkeypatch.setattr(
        auth_routes,
        "_OAUTH_CALLBACK_THROTTLE",
        AuthThrottle(auth_routes._OAUTH_START_LIMITS),
    )

    idp = FakeIdentityProvider()
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    links = HiveIdentityLinkStore()

    def build() -> EntraHarness:
        return EntraHarness(
            idp=idp,
            http=http,
            links=links,
            service=OAuthLoginService(get_settings(), http=http, link_store=links),
        )

    harness = build()
    monkeypatch.setattr(auth_routes, "get_oauth_login_service", lambda: harness.service)
    harness.rebuild = build  # type: ignore[attr-defined]
    return harness, snapshots  # type: ignore[return-value]


@pytest.fixture
def entra_harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[EntraHarness]:
    harness, snapshots = _make_harness(monkeypatch, _entra_provider_document())
    yield harness
    asyncio.run(harness.http.aclose())
    _restore_store(stores.oauth_identity_links, snapshots["links"])
    _restore_store(stores.sessions, snapshots["sessions"])
    _restore_store(stores.audit_log, snapshots["audit"])
    _restore_store(stores.users, snapshots["users"])
    get_settings.cache_clear()


@pytest.fixture
def hybrid_harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[EntraHarness]:
    harness, snapshots = _make_harness(monkeypatch, _hybrid_provider_document())
    yield harness
    asyncio.run(harness.http.aclose())
    _restore_store(stores.oauth_identity_links, snapshots["links"])
    _restore_store(stores.sessions, snapshots["sessions"])
    _restore_store(stores.audit_log, snapshots["audit"])
    _restore_store(stores.users, snapshots["users"])
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_login_throttle() -> Iterator[None]:
    """A clean budget per test, like the throttle suite: module singletons are
    right for a running server and wrong for a suite."""
    auth_routes._LOGIN_THROTTLE = AuthThrottle()
    yield


def _client() -> TestClient:
    return TestClient(app, base_url=_PUBLIC_ORIGIN)


def _begin(client: TestClient, provider: str = "entra") -> tuple[str, str]:
    response = client.get(f"/v1/auth/oauth/{provider}/start", follow_redirects=False)
    assert response.status_code == 303, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0], query["nonce"][0]


def _callback(client: TestClient, provider: str, code: str, state: str) -> httpx.Response:
    return client.get(
        f"/v1/auth/oauth/{provider}/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )


def _audit_actions() -> list[str]:
    return [
        str(entry.get("action")) for entry in stores.audit_log.values() if isinstance(entry, dict)
    ]


class TestEntraProviderSettings:
    def test_an_entra_provider_needs_only_a_tenant_and_client_id(self) -> None:
        provider = OAuthProviderSettings(
            client_id=_ENTRA_CLIENT_ID,
            entra_tenant_id=_ENTRA_TENANT.upper(),
        )
        assert provider.entra_tenant_id == _ENTRA_TENANT

    @pytest.mark.parametrize("alias", ["common", "organizations", "consumers", "not-a-uuid"])
    def test_multi_tenant_aliases_are_refused(self, alias: str) -> None:
        with pytest.raises(ValidationError, match="one concrete directory UUID"):
            OAuthProviderSettings(client_id=_ENTRA_CLIENT_ID, entra_tenant_id=alias)

    def test_a_generic_provider_still_requires_all_four_endpoints(self) -> None:
        with pytest.raises(ValidationError, match="are required unless entra_tenant_id"):
            OAuthProviderSettings(client_id="some-client")

    def test_an_entra_provider_may_not_also_pin_endpoints(self) -> None:
        with pytest.raises(ValidationError, match="do not also set"):
            OAuthProviderSettings(
                client_id=_ENTRA_CLIENT_ID,
                entra_tenant_id=_ENTRA_TENANT,
                authorization_url=_ENTRA_AUTHORIZATION_URL,
                token_url=_ENTRA_TOKEN_URL,
                jwks_url=_ENTRA_JWKS_URL,
                issuer=_ENTRA_ISSUER,
            )

    def test_the_default_login_mode_is_hybrid(self) -> None:
        # `hybrid` is the compatibility default: existing generic-OAuth
        # deployments keep their providers and local-only deployments behave
        # exactly as before (no providers configured).
        assert Settings(_env_file=None).human_auth_mode == "hybrid"

    @pytest.mark.parametrize("mode", ["local", "hybrid"])
    def test_only_the_three_named_modes_are_admitted(self, mode: str) -> None:
        assert Settings(_env_file=None, human_auth_mode=mode).human_auth_mode == mode

    def test_entra_mode_is_admitted_with_its_single_required_provider(self) -> None:
        settings = Settings(
            _env_file=None,
            human_auth_mode="entra",
            oauth_providers=_entra_provider_document(),
            oauth_public_origin=_PUBLIC_ORIGIN,
        )
        assert settings.human_auth_mode == "entra"

    def test_an_unnamed_mode_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, human_auth_mode="passwords")


class TestEntraProductWiring:
    @pytest.mark.contract("boundary")
    @pytest.mark.contract("behavioral")
    def test_the_service_builds_tenant_specific_v2_endpoints(
        self, entra_harness: EntraHarness
    ) -> None:
        config = entra_harness.service._core_provider(
            "entra", get_settings().oauth_providers["entra"]
        )
        assert config.authorization_url == _ENTRA_AUTHORIZATION_URL
        assert config.token_url == _ENTRA_TOKEN_URL
        assert config.jwks_url == _ENTRA_JWKS_URL
        assert config.issuer == _ENTRA_ISSUER
        assert config.userinfo_url is None
        assert config.require_id_token is True

    @pytest.mark.contract("boundary")
    @pytest.mark.contract("behavioral")
    def test_entra_login_links_the_immutable_tenant_object_pair(
        self, entra_harness: EntraHarness
    ) -> None:
        asyncio.run(entra_harness.links.link("entra", _ENTRA_SUBJECT, "user"))
        client = _client()
        before = set(stores.sessions.keys())
        state, nonce = _begin(client)
        entra_harness.idp.codes["entra-code"] = {
            "access_token": "sentinel-access",
            "token_type": "Bearer",
            "id_token": _entra_id_token(nonce),
        }

        callback = _callback(client, "entra", "entra-code", state)

        assert callback.status_code == 303
        assert callback.headers["location"] == "/"
        assert len(set(stores.sessions.keys()) - before) == 1
        login_events = [
            entry
            for entry in stores.audit_log.values()
            if isinstance(entry, dict) and entry.get("action") == "auth.oauth.login"
        ]
        assert login_events[0]["detail"]["subject"] == _ENTRA_SUBJECT

    @pytest.mark.contract("boundary")
    @pytest.mark.contract("behavioral")
    def test_a_token_from_another_tenant_is_refused(self, entra_harness: EntraHarness) -> None:
        asyncio.run(entra_harness.links.link("entra", _ENTRA_SUBJECT, "user"))
        client = _client()
        before = set(stores.sessions.keys())
        state, nonce = _begin(client)
        entra_harness.idp.codes["wrong-tenant"] = {
            "access_token": "sentinel-access",
            "token_type": "Bearer",
            "id_token": _entra_id_token(nonce, tid=_OTHER_TENANT),
        }

        callback = _callback(client, "entra", "wrong-tenant", state)

        assert callback.status_code == 401
        assert callback.json() == {"detail": "OAuth authentication failed"}
        assert set(stores.sessions.keys()) == before
        assert (
            stores.oauth_identity_links.get(
                _identity_link_key("entra", f"{_OTHER_TENANT}:{_ENTRA_OID}")
            )
            is None
        )

    @pytest.mark.contract("boundary")
    @pytest.mark.contract("behavioral")
    def test_hybrid_deployments_keep_generic_providers_on_the_generic_verifier(
        self, hybrid_harness: EntraHarness
    ) -> None:
        asyncio.run(hybrid_harness.links.link(_GENERIC_PROVIDER, _GENERIC_SUB, "user"))
        client = _client()
        before = set(stores.sessions.keys())
        state, nonce = _begin(client, _GENERIC_PROVIDER)
        hybrid_harness.idp.codes["generic-code"] = {
            "access_token": "sentinel-access",
            "token_type": "Bearer",
            "id_token": _id_token(
                nonce,
                issuer=_GENERIC_ISSUER,
                audience=_GENERIC_CLIENT_ID,
                subject=_GENERIC_SUB,
                extra_claims={},
            ),
        }

        callback = _callback(client, _GENERIC_PROVIDER, "generic-code", state)

        assert callback.status_code == 303
        assert len(set(stores.sessions.keys()) - before) == 1


class TestLoginModePolicyIsReachedByTheRoute:
    @pytest.fixture
    def password_user(self) -> Iterator[str]:
        from datetime import UTC, datetime

        from maistro.security.passwords import hash_password

        stores.users["entra-mode-user"] = stores.users._model_class(
            id="entra-mode-user",
            username="entra-mode-user",
            password_hash=hash_password("correct-horse-battery"),
            role="user",
            is_active=True,
            permissions=[],
            created_at=datetime.now(UTC),
        )
        yield "entra-mode-user"
        stores.users.pop("entra-mode-user", None)

    def test_entra_only_mode_denies_ordinary_password_login(
        self, monkeypatch: pytest.MonkeyPatch, password_user: str
    ) -> None:
        monkeypatch.setenv("HUMAN_AUTH_MODE", "entra")
        monkeypatch.setenv("OAUTH_PROVIDERS", json.dumps(_entra_provider_document()))
        monkeypatch.setenv("OAUTH_PUBLIC_ORIGIN", _PUBLIC_ORIGIN)
        get_settings.cache_clear()
        client = _client()
        before = set(stores.sessions.keys())

        response = client.post(
            "/v1/auth/login",
            json={"username": password_user, "password": "correct-horse-battery"},
        )

        assert response.status_code == 403
        assert response.json() == {"detail": "Password login is disabled for this deployment."}
        assert set(stores.sessions.keys()) == before
        assert "login_auth_mode_denied" in _audit_actions()

    def test_the_denial_cannot_be_weakened_from_the_request(
        self, monkeypatch: pytest.MonkeyPatch, password_user: str
    ) -> None:
        monkeypatch.setenv("HUMAN_AUTH_MODE", "entra")
        monkeypatch.setenv("OAUTH_PROVIDERS", json.dumps(_entra_provider_document()))
        monkeypatch.setenv("OAUTH_PUBLIC_ORIGIN", _PUBLIC_ORIGIN)
        get_settings.cache_clear()
        client = _client()
        before = set(stores.sessions.keys())

        response = client.post(
            "/v1/auth/login",
            json={
                "username": password_user,
                "password": "correct-horse-battery",
                "break_glass": True,
            },
        )

        assert response.status_code in (403, 422)
        assert set(stores.sessions.keys()) == before

    def test_local_mode_keeps_password_login(
        self, monkeypatch: pytest.MonkeyPatch, password_user: str
    ) -> None:
        monkeypatch.setenv("HUMAN_AUTH_MODE", "local")
        get_settings.cache_clear()
        client = _client()

        response = client.post(
            "/v1/auth/login",
            json={"username": password_user, "password": "correct-horse-battery"},
        )

        assert response.status_code == 200
        assert "hive_session=" in response.headers.get("set-cookie", "")

    def test_hybrid_mode_keeps_password_login(
        self, monkeypatch: pytest.MonkeyPatch, password_user: str
    ) -> None:
        monkeypatch.setenv("HUMAN_AUTH_MODE", "hybrid")
        get_settings.cache_clear()
        client = _client()

        response = client.post(
            "/v1/auth/login",
            json={"username": password_user, "password": "correct-horse-battery"},
        )

        assert response.status_code == 200
        assert "hive_session=" in response.headers.get("set-cookie", "")

    def test_the_default_mode_changes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, password_user: str
    ) -> None:
        monkeypatch.delenv("HUMAN_AUTH_MODE", raising=False)
        get_settings.cache_clear()
        client = _client()

        response = client.post(
            "/v1/auth/login",
            json={"username": password_user, "password": "correct-horse-battery"},
        )

        assert response.status_code == 200
