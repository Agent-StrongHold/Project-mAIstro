"""Tests for maistro.auth.oauth — OAuth2 Authorization Code + PKCE (SPEC-183 / ADR-059).

Negative tests are first-class: no code path may yield a token/identity
without a verified provider response.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from maistro.auth.oauth import (
    IdentityLinker,
    InMemoryIdentityLinkStore,
    InMemoryStateStore,
    JWKSIdTokenVerifier,
    OAuth2Client,
    OAuthError,
    OAuthExchangeError,
    OAuthIdentity,
    OAuthProviderConfig,
    OAuthStateEntry,
    OAuthStateError,
    OAuthToken,
    OAuthTokenValidationError,
    UnverifiedJWTClaimsValidator,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

ISSUER = "https://idp.example.com"
CLIENT_ID = "maistro-client"
TOKEN_URL = "https://idp.example.com/token"
JWKS_URL = "https://idp.example.com/jwks"
USERINFO_URL = "https://idp.example.com/userinfo"
AUTHZ_URL = "https://idp.example.com/authorize"
REDIRECT_URI = "https://conductor.local/v1/auth/oauth/test/callback"

_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key-1"


def _jwks() -> dict[str, Any]:
    pub = _RSA_KEY.public_key().public_numbers()

    def b64(n: int, length: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": _KID,
                "use": "sig",
                "alg": "RS256",
                "n": b64(pub.n, 256),
                "e": b64(pub.e, 3),
            }
        ]
    }


def make_id_token(**overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "sub-123",
        "exp": now + 300,
        "iat": now,
        "email": "alice@example.com",
        "email_verified": True,
        "name": "Alice",
    }
    claims.update(overrides)
    key = overrides.pop("_key", _RSA_KEY)
    return pyjwt.encode(claims, key, algorithm="RS256", headers={"kid": _KID})


def provider_config(**overrides: Any) -> OAuthProviderConfig:
    kwargs: dict[str, Any] = {
        "name": "test",
        "authorization_url": AUTHZ_URL,
        "token_url": TOKEN_URL,
        "client_id": CLIENT_ID,
        "jwks_url": JWKS_URL,
        "userinfo_url": USERINFO_URL,
        "issuer": ISSUER,
    }
    kwargs.update(overrides)
    return OAuthProviderConfig(**kwargs)


class FakeIdP:
    """MockTransport handler simulating the provider's token/jwks/userinfo endpoints."""

    def __init__(self) -> None:
        self.valid_codes: dict[str, dict[str, Any]] = {}  # code -> token response
        self.userinfo: dict[str, Any] = {"sub": "sub-123", "name": "Alice"}
        self.refresh_response: dict[str, Any] | None = None
        self.token_requests: list[dict[str, str]] = []
        self.jwks_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == JWKS_URL:
            return httpx.Response(self.jwks_status, json=_jwks())
        if url == USERINFO_URL:
            return httpx.Response(200, json=self.userinfo)
        if url == TOKEN_URL:
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if form.get("grant_type") == "refresh_token":
                if self.refresh_response is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self.refresh_response)
            code = form.get("code", "")
            body = self.valid_codes.pop(code, None)  # codes are single-use
            if body is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=body)
        return httpx.Response(404)


def make_client(
    idp: FakeIdP,
    *,
    config: OAuthProviderConfig | None = None,
    state_store: InMemoryStateStore | None = None,
    secret: str | None = "shh-client-secret",
    verifier: Any = None,
    events: list[tuple[str, dict[str, Any]]] | None = None,
    state_ttl: float = 600.0,
    clock: Any = time.monotonic,
) -> OAuth2Client:
    cfg = config or provider_config()
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    return OAuth2Client(
        providers={cfg.name: cfg},
        state_store=state_store or InMemoryStateStore(),
        http=http,
        secret_resolver=lambda name: secret,
        id_token_verifier=verifier or JWKSIdTokenVerifier(),
        event_emitter=(lambda name, payload: events.append((name, payload)))
        if events is not None
        else None,
        state_ttl_seconds=state_ttl,
        clock=clock,
    )


async def start_flow(client: OAuth2Client, provider: str = "test") -> tuple[str, str, str]:
    """Run authorize_url; return (state, nonce_from_url, challenge)."""
    url, state = await client.authorize_url(provider, REDIRECT_URI)
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    return state, q["nonce"], q["code_challenge"]


# ---------------------------------------------------------------------------
# authorize_url — state + PKCE S256
# ---------------------------------------------------------------------------


async def test_authorize_url_has_pkce_s256_state_and_nonce() -> None:
    store = InMemoryStateStore()
    client = make_client(FakeIdP(), state_store=store)
    url, state = await client.authorize_url("test", REDIRECT_URI)
    parsed = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert url.startswith(AUTHZ_URL + "?")
    assert q["response_type"] == "code"
    assert q["client_id"] == CLIENT_ID
    assert q["redirect_uri"] == REDIRECT_URI
    assert q["state"] == state
    assert q["code_challenge_method"] == "S256"
    assert q["scope"] == "openid profile email"
    # the challenge must be S256(verifier) of the server-side stored verifier
    entry = await store.consume(state)
    assert entry is not None
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(entry.code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert q["code_challenge"] == expected
    assert 43 <= len(entry.code_verifier) <= 128  # RFC 7636
    assert q["nonce"] == entry.nonce


async def test_authorize_url_unknown_provider_raises() -> None:
    client = make_client(FakeIdP())
    with pytest.raises(OAuthError):
        await client.authorize_url("nope", REDIRECT_URI)


async def test_authorize_url_states_are_unique() -> None:
    client = make_client(FakeIdP())
    _, s1 = await client.authorize_url("test", REDIRECT_URI)
    _, s2 = await client.authorize_url("test", REDIRECT_URI)
    assert s1 != s2


# ---------------------------------------------------------------------------
# exchange_code — happy path
# ---------------------------------------------------------------------------


async def test_exchange_code_happy_path_returns_verified_identity() -> None:
    idp = FakeIdP()
    events: list[tuple[str, dict[str, Any]]] = []
    client = make_client(idp, events=events)
    state, nonce, _ = await start_flow(client)
    idp.valid_codes["good-code"] = {
        "access_token": "at-secret",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "rt-secret",
        "id_token": make_id_token(nonce=nonce),
    }
    exchange = await client.exchange_code("test", "good-code", state, REDIRECT_URI)
    assert exchange.identity == OAuthIdentity(
        provider="test",
        sub="sub-123",
        email="alice@example.com",
        email_verified=True,
        display_name="Alice",
    )
    assert exchange.token.access_token == "at-secret"
    assert exchange.token.refresh_token == "rt-secret"
    assert exchange.token.expires_in == 3600
    # PKCE verifier and secret were sent to the token endpoint
    form = idp.token_requests[-1]
    assert form["grant_type"] == "authorization_code"
    assert "code_verifier" in form
    assert form["client_secret"] == "shh-client-secret"
    # audit event emitted, and no token material in any event payload
    assert ("auth.oauth.login", {"provider": "test", "sub": "sub-123"}) in events
    dumped = json.dumps([p for _, p in events])
    assert "at-secret" not in dumped and "rt-secret" not in dumped


async def test_exchange_code_without_id_token_falls_back_to_userinfo() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    state, _, _ = await start_flow(client)
    idp.userinfo = {"id": "gh-42", "name": "Bob", "email": "bob@example.com"}
    idp.valid_codes["c"] = {"access_token": "at", "token_type": "bearer"}
    exchange = await client.exchange_code("test", "c", state, REDIRECT_URI)
    assert exchange.identity.sub == "gh-42"
    assert exchange.identity.display_name == "Bob"
    assert exchange.identity.email_verified is False


async def test_exchange_code_no_sub_anywhere_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    state, _, _ = await start_flow(client)
    idp.userinfo = {"name": "Nameless"}
    idp.valid_codes["c"] = {"access_token": "at", "token_type": "bearer"}
    with pytest.raises(OAuthExchangeError, match="no stable subject"):
        await client.exchange_code("test", "c", state, REDIRECT_URI)


# ---------------------------------------------------------------------------
# exchange_code — negative: bad/replayed code or state -> raises, NO token
# ---------------------------------------------------------------------------


async def test_unknown_state_raises_and_never_contacts_provider() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    with pytest.raises(OAuthStateError):
        await client.exchange_code("test", "any-code", "forged-state", REDIRECT_URI)
    assert idp.token_requests == []  # no token POST was even attempted


async def test_replayed_state_raises_second_time() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    state, nonce, _ = await start_flow(client)
    body = {
        "access_token": "at",
        "token_type": "Bearer",
        "id_token": make_id_token(nonce=nonce),
    }
    idp.valid_codes["c1"] = dict(body)
    await client.exchange_code("test", "c1", state, REDIRECT_URI)
    idp.valid_codes["c2"] = dict(body)
    with pytest.raises(OAuthStateError):
        await client.exchange_code("test", "c2", state, REDIRECT_URI)


async def test_expired_state_ttl_raises() -> None:
    fake_now = [1000.0]
    store = InMemoryStateStore(clock=lambda: fake_now[0])
    idp = FakeIdP()
    client = make_client(idp, state_store=store, state_ttl=60.0, clock=lambda: fake_now[0])
    state, _, _ = await start_flow(client)
    fake_now[0] += 61.0  # past TTL
    with pytest.raises(OAuthStateError):
        await client.exchange_code("test", "c", state, REDIRECT_URI)
    assert idp.token_requests == []


async def test_state_provider_mismatch_raises() -> None:
    idp = FakeIdP()
    other = provider_config(name="other")
    cfg = provider_config()
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    client = OAuth2Client(
        providers={"test": cfg, "other": other},
        state_store=InMemoryStateStore(),
        http=http,
        secret_resolver=lambda name: None,
    )
    state, _, _ = await start_flow(client, provider="test")
    with pytest.raises(OAuthStateError):
        await client.exchange_code("other", "c", state, REDIRECT_URI)


async def test_state_redirect_uri_mismatch_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    state, _, _ = await start_flow(client)
    with pytest.raises(OAuthStateError):
        await client.exchange_code("test", "c", state, "https://evil.example.com/cb")
    assert idp.token_requests == []


async def test_bad_code_provider_rejection_raises_no_token() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    state, _, _ = await start_flow(client)
    with pytest.raises(OAuthExchangeError, match="invalid_grant"):
        await client.exchange_code("test", "wrong-code", state, REDIRECT_URI)


async def test_replayed_code_raises_no_token() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    s1, n1, _ = await start_flow(client)
    idp.valid_codes["once"] = {
        "access_token": "at",
        "token_type": "Bearer",
        "id_token": make_id_token(nonce=n1),
    }
    await client.exchange_code("test", "once", s1, REDIRECT_URI)
    s2, _, _ = await start_flow(client)  # fresh state, replayed code
    with pytest.raises(OAuthExchangeError):
        await client.exchange_code("test", "once", s2, REDIRECT_URI)


async def test_token_response_missing_access_token_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    state, _, _ = await start_flow(client)
    idp.valid_codes["c"] = {"token_type": "Bearer"}
    with pytest.raises(OAuthExchangeError, match="no access_token"):
        await client.exchange_code("test", "c", state, REDIRECT_URI)


async def test_unknown_provider_exchange_raises() -> None:
    client = make_client(FakeIdP())
    with pytest.raises(OAuthError):
        await client.exchange_code("nope", "c", "s", REDIRECT_URI)


# ---------------------------------------------------------------------------
# OIDC id_token validation failures
# ---------------------------------------------------------------------------


async def _exchange_with_id_token(idp: FakeIdP, client: OAuth2Client, id_token: str) -> None:
    state, _, _ = await start_flow(client)
    idp.valid_codes["c"] = {"access_token": "at", "token_type": "Bearer", "id_token": id_token}
    await client.exchange_code("test", "c", state, REDIRECT_URI)


async def test_id_token_bad_signature_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad = pyjwt.encode(
        {"iss": ISSUER, "aud": CLIENT_ID, "sub": "s", "exp": int(time.time()) + 300},
        wrong_key,
        algorithm="RS256",
        headers={"kid": _KID},
    )
    with pytest.raises(OAuthTokenValidationError):
        await _exchange_with_id_token(idp, client, bad)


async def test_id_token_tampered_payload_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    state, nonce, _ = await start_flow(client)
    token = make_id_token(nonce=nonce)
    h, p, s = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    claims["sub"] = "attacker"
    p2 = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    idp.valid_codes["c"] = {
        "access_token": "at",
        "token_type": "Bearer",
        "id_token": f"{h}.{p2}.{s}",
    }
    with pytest.raises(OAuthTokenValidationError):
        await client.exchange_code("test", "c", state, REDIRECT_URI)


async def test_id_token_wrong_issuer_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    with pytest.raises(OAuthTokenValidationError):
        await _exchange_with_id_token(idp, client, make_id_token(iss="https://evil.example.com"))


async def test_id_token_wrong_audience_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    with pytest.raises(OAuthTokenValidationError):
        await _exchange_with_id_token(idp, client, make_id_token(aud="someone-else"))


async def test_id_token_expired_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    with pytest.raises(OAuthTokenValidationError):
        await _exchange_with_id_token(idp, client, make_id_token(exp=int(time.time()) - 60))


async def test_id_token_nonce_mismatch_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    with pytest.raises(OAuthTokenValidationError):
        await _exchange_with_id_token(idp, client, make_id_token(nonce="stolen-different-nonce"))


async def test_id_token_unknown_kid_raises() -> None:
    idp = FakeIdP()
    client = make_client(idp)
    token = pyjwt.encode(
        {"iss": ISSUER, "aud": CLIENT_ID, "sub": "s", "exp": int(time.time()) + 300},
        _RSA_KEY,
        algorithm="RS256",
        headers={"kid": "not-in-jwks"},
    )
    with pytest.raises(OAuthTokenValidationError):
        await _exchange_with_id_token(idp, client, token)


async def test_jwks_fetch_failure_raises() -> None:
    idp = FakeIdP()
    idp.jwks_status = 500
    client = make_client(idp)
    with pytest.raises(OAuthTokenValidationError, match="JWKS"):
        await _exchange_with_id_token(idp, client, make_id_token())


async def test_jwks_verifier_requires_jwks_url() -> None:
    idp = FakeIdP()
    client = make_client(idp, config=provider_config(jwks_url=None))
    with pytest.raises(OAuthTokenValidationError, match="no jwks_url"):
        await _exchange_with_id_token(idp, client, make_id_token())


# ---------------------------------------------------------------------------
# UnverifiedJWTClaimsValidator (claims-only fallback) — still enforces claims
# ---------------------------------------------------------------------------


def _claims_token(**overrides: Any) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "s",
        "exp": int(time.time()) + 300,
    }
    claims.update(overrides)
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"e30.{payload}.sig"


async def test_claims_validator_accepts_valid_claims() -> None:
    v = UnverifiedJWTClaimsValidator()
    async with httpx.AsyncClient(transport=httpx.MockTransport(FakeIdP().handler)) as http:
        claims = await v.verify(_claims_token(nonce="n1"), provider_config(), http, "n1")
    assert claims["sub"] == "s"


@pytest.mark.parametrize(
    "bad",
    [
        {"iss": "https://evil.example.com"},
        {"aud": "someone-else"},
        {"exp": int(time.time()) - 10},
        {"nonce": "wrong"},
    ],
)
async def test_claims_validator_rejects_bad_claims(bad: dict[str, Any]) -> None:
    v = UnverifiedJWTClaimsValidator()
    async with httpx.AsyncClient(transport=httpx.MockTransport(FakeIdP().handler)) as http:
        with pytest.raises(OAuthTokenValidationError):
            await v.verify(_claims_token(**{"nonce": "n1", **bad}), provider_config(), http, "n1")


async def test_claims_validator_rejects_non_jwt() -> None:
    v = UnverifiedJWTClaimsValidator()
    async with httpx.AsyncClient(transport=httpx.MockTransport(FakeIdP().handler)) as http:
        with pytest.raises(OAuthTokenValidationError):
            await v.verify("not-a-jwt", provider_config(), http, None)


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


async def test_refresh_returns_new_token() -> None:
    idp = FakeIdP()
    idp.refresh_response = {
        "access_token": "new-at",
        "token_type": "Bearer",
        "expires_in": 1800,
        "refresh_token": "new-rt",
    }
    events: list[tuple[str, dict[str, Any]]] = []
    client = make_client(idp, events=events)
    token = await client.refresh("test", "old-rt")
    assert token == OAuthToken(
        access_token="new-at", token_type="Bearer", expires_in=1800, refresh_token="new-rt"
    )
    assert idp.token_requests[-1]["refresh_token"] == "old-rt"
    assert ("auth.oauth.refresh", {"provider": "test"}) in events
    assert "new-at" not in json.dumps([p for _, p in events])


async def test_refresh_rejected_raises() -> None:
    idp = FakeIdP()  # refresh_response=None -> invalid_grant
    client = make_client(idp)
    with pytest.raises(OAuthExchangeError):
        await client.refresh("test", "revoked-rt")


# ---------------------------------------------------------------------------
# InMemoryStateStore semantics
# ---------------------------------------------------------------------------


def _entry(expires_at: float) -> OAuthStateEntry:
    return OAuthStateEntry(
        provider="test",
        code_verifier="v" * 43,
        redirect_uri=REDIRECT_URI,
        nonce="n",
        expires_at=expires_at,
    )


async def test_state_store_consume_is_single_use() -> None:
    store = InMemoryStateStore()
    await store.put("s", _entry(time.monotonic() + 60))
    assert await store.consume("s") is not None
    assert await store.consume("s") is None


async def test_state_store_expired_entry_is_none_and_gone() -> None:
    now = [100.0]
    store = InMemoryStateStore(clock=lambda: now[0])
    await store.put("s", _entry(150.0))
    now[0] = 150.0  # exactly at expiry -> expired
    assert await store.consume("s") is None
    assert await store.consume("s") is None


# ---------------------------------------------------------------------------
# Identity linking (Phase 2)
# ---------------------------------------------------------------------------


def identity(sub: str = "sub-123", email: str | None = "alice@example.com") -> OAuthIdentity:
    return OAuthIdentity(
        provider="test", sub=sub, email=email, email_verified=True, display_name="Alice"
    )


async def test_known_link_resolves_to_that_user() -> None:
    store = InMemoryIdentityLinkStore()
    await store.link("test", "sub-123", "hive-user-7")
    linker = IdentityLinker(store=store)
    assert await linker.resolve_user(identity()) == "hive-user-7"


async def test_unknown_identity_without_open_registration_is_none() -> None:
    linker = IdentityLinker(store=InMemoryIdentityLinkStore(), open_registration=False)
    assert await linker.resolve_user(identity()) is None


async def test_unknown_identity_with_registration_but_no_provisioner_is_none() -> None:
    linker = IdentityLinker(store=InMemoryIdentityLinkStore(), open_registration=True)
    assert await linker.resolve_user(identity()) is None


async def test_first_time_identity_provisioned_as_plain_user_no_admin() -> None:
    """First-time identity gets a role='user', empty-permissions record; the
    provisioner receives only the identity — no role/permission escalation
    surface exists for core to grant admin."""
    created: list[OAuthIdentity] = []
    users: dict[str, dict[str, Any]] = {}

    async def provision(ident: OAuthIdentity) -> str:
        created.append(ident)
        uid = f"u-{len(users) + 1}"
        users[uid] = {"role": "user", "permissions": []}  # product contract
        return uid

    store = InMemoryIdentityLinkStore()
    events: list[tuple[str, dict[str, Any]]] = []
    linker = IdentityLinker(
        store=store,
        provision_user=provision,
        open_registration=True,
        event_emitter=lambda n, p: events.append((n, p)),
    )
    uid = await linker.resolve_user(identity())
    assert uid == "u-1"
    assert users[uid] == {"role": "user", "permissions": []}
    assert created == [identity()]
    # link persisted: second login resolves without provisioning again
    assert await linker.resolve_user(identity()) == "u-1"
    assert len(created) == 1
    assert ("auth.oauth.link", {"provider": "test", "sub": "sub-123", "user_id": "u-1"}) in events


async def test_email_is_never_the_join_key() -> None:
    """Same email, different (provider, sub) must NOT resolve to the linked user."""
    store = InMemoryIdentityLinkStore()
    await store.link("test", "sub-123", "victim-user")
    linker = IdentityLinker(store=store)
    attacker = identity(sub="attacker-sub", email="alice@example.com")
    assert await linker.resolve_user(attacker) is None
    # and different provider with the same sub is also distinct
    assert await store.resolve("other-provider", "sub-123") is None


async def test_explicit_link_current_user() -> None:
    store = InMemoryIdentityLinkStore()
    events: list[tuple[str, dict[str, Any]]] = []
    linker = IdentityLinker(store=store, event_emitter=lambda n, p: events.append((n, p)))
    await linker.link_current_user(identity(sub="gh-9"), "hive-user-3")
    assert await store.resolve("test", "gh-9") == "hive-user-3"
    assert await linker.resolve_user(identity(sub="gh-9")) == "hive-user-3"
    assert ("auth.oauth.link", {"provider": "test", "sub": "gh-9", "user_id": "hive-user-3"}) in (
        events
    )


# ---------------------------------------------------------------------------
# Package exports
# ---------------------------------------------------------------------------


def test_oauth_exports_available_from_maistro_auth() -> None:
    import maistro.auth as auth_pkg

    assert auth_pkg.OAuth2Client is OAuth2Client
    assert auth_pkg.OAuthProviderConfig is OAuthProviderConfig
    assert auth_pkg.IdentityLinker is IdentityLinker
