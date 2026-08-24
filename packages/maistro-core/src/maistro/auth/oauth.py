"""OAuth2 Authorization Code + PKCE user authentication (ADR-059 / SPEC-183).

Real provider flow replacing the deleted ``maistro.security.oauth`` fabricating
stub. This module provides *authentication only*: it verifies who the user is
against an external IdP. Authorization (permissions, roles, sessions) remains
the product's concern (e.g. hive-conductor's ``HiveUser`` + ``hive_session``).

Security invariants (tested):
- No identity is ever returned without a verified provider response.
- ``state`` is single-use and TTL-bound; replay or expiry raises.
- PKCE ``code_challenge`` is always S256.
- OIDC ``id_token`` issuer/audience/expiry/nonce are always validated; the
  signature is validated against the provider JWKS when PyJWT is available
  (see ``JWKSIdTokenVerifier`` / ``UnverifiedJWTClaimsValidator``).
- Client secrets are resolved via an injected callable, never stored on config.
- Tokens are never placed in emitted events or logs (ADR-044).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from maistro.security.outbound import configure_outbound_policy

logger = logging.getLogger("maistro.auth.oauth")

__all__ = [
    "IdTokenVerifier",
    "IdentityLinkStore",
    "IdentityLinker",
    "InMemoryIdentityLinkStore",
    "InMemoryStateStore",
    "JWKSIdTokenVerifier",
    "OAuth2Client",
    "OAuthError",
    "OAuthExchange",
    "OAuthExchangeError",
    "OAuthIdentity",
    "OAuthProviderConfig",
    "OAuthStateEntry",
    "OAuthStateError",
    "OAuthToken",
    "OAuthTokenValidationError",
    "StateStore",
    "UnverifiedJWTClaimsValidator",
    "begin_login",
    "complete_login",
    "default_id_token_verifier",
]

# Type of the injected secret resolver: provider name -> client_secret (or
# None for public clients). Secrets never live on OAuthProviderConfig.
SecretResolver = Callable[[str], str | None]

# Optional audit-event sink: (event_name, payload). Payloads never carry tokens.
EventEmitter = Callable[[str, dict[str, Any]], None]


class OAuthError(Exception):
    """Base class for OAuth failures. No token/identity is produced on raise."""


class OAuthStateError(OAuthError):
    """Unknown, replayed, expired, or mismatched ``state``."""


class OAuthExchangeError(OAuthError):
    """The provider rejected the code/refresh exchange (or returned garbage)."""


class OAuthTokenValidationError(OAuthError):
    """The OIDC ``id_token`` failed validation."""


@dataclass(frozen=True)
class OAuthProviderConfig:
    """Static provider description. ``client_secret`` is deliberately absent —
    it is resolved at call time via the injected secret resolver."""

    name: str
    authorization_url: str
    token_url: str
    client_id: str
    jwks_url: str | None = None
    userinfo_url: str | None = None
    issuer: str | None = None
    scopes: tuple[str, ...] = ("openid", "profile", "email")


@dataclass(frozen=True)
class OAuthToken:
    """Provider token set. Treat as a secret: never log, never emit."""

    access_token: str
    token_type: str
    expires_in: int | None = None
    refresh_token: str | None = None
    scope: str | None = None
    id_token: str | None = None


@dataclass(frozen=True)
class OAuthIdentity:
    provider: str
    sub: str
    email: str | None = None
    email_verified: bool = False
    display_name: str | None = None


@dataclass(frozen=True)
class OAuthExchange:
    """Result of a successful code exchange: verified identity + provider tokens."""

    identity: OAuthIdentity
    token: OAuthToken


@dataclass(frozen=True)
class OAuthStateEntry:
    provider: str
    code_verifier: str
    redirect_uri: str
    nonce: str
    expires_at: float


@runtime_checkable
class StateStore(Protocol):
    """Server-side, single-use, TTL-bound state storage."""

    async def put(self, state: str, entry: OAuthStateEntry) -> None: ...

    async def consume(self, state: str) -> OAuthStateEntry | None:
        """Atomically remove and return the entry (None if unknown). A second
        consume of the same state MUST return None (replay protection)."""
        ...


class InMemoryStateStore:
    """Default in-process StateStore with TTL expiry on consume."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: dict[str, OAuthStateEntry] = {}
        self._clock = clock

    async def put(self, state: str, entry: OAuthStateEntry) -> None:
        self._entries[state] = entry

    async def consume(self, state: str) -> OAuthStateEntry | None:
        entry = self._entries.pop(state, None)
        if entry is None:
            return None
        if self._clock() >= entry.expires_at:
            return None  # expired: gone either way (single use)
        return entry


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _validate_oidc_claims(
    claims: dict[str, Any],
    config: OAuthProviderConfig,
    nonce: str | None,
    now: float,
) -> None:
    """Issuer / audience / expiry / nonce checks shared by both verifiers."""
    if config.issuer is not None and claims.get("iss") != config.issuer:
        raise OAuthTokenValidationError(
            f"id_token issuer mismatch: expected {config.issuer!r}, got {claims.get('iss')!r}"
        )
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if config.client_id not in audiences:
        raise OAuthTokenValidationError("id_token audience does not include our client_id")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or now >= float(exp):
        raise OAuthTokenValidationError("id_token is expired or has no exp claim")
    if nonce is not None and claims.get("nonce") != nonce:
        raise OAuthTokenValidationError("id_token nonce mismatch")


@runtime_checkable
class IdTokenVerifier(Protocol):
    """Seam for OIDC id_token validation."""

    async def verify(
        self,
        id_token: str,
        config: OAuthProviderConfig,
        http: httpx.AsyncClient,
        nonce: str | None,
    ) -> dict[str, Any]:
        """Return validated claims, or raise OAuthTokenValidationError."""
        ...


class JWKSIdTokenVerifier:
    """Full OIDC verification: JWKS signature + issuer/audience/expiry/nonce.

    Requires PyJWT with its ``crypto`` extra (``cryptography`` is already a
    maistro-core dependency; PyJWT itself arrives transitively via the ``llm``
    extra). Import is lazy so the module stays importable without it.
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    async def verify(
        self,
        id_token: str,
        config: OAuthProviderConfig,
        http: httpx.AsyncClient,
        nonce: str | None,
    ) -> dict[str, Any]:
        try:
            import jwt as pyjwt
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise OAuthTokenValidationError(
                "JWKSIdTokenVerifier requires PyJWT; install pyjwt[crypto] or "
                "inject UnverifiedJWTClaimsValidator explicitly."
            ) from exc
        if not config.jwks_url:
            raise OAuthTokenValidationError(
                f"provider {config.name!r} has no jwks_url; cannot verify id_token signature"
            )
        try:
            resp = await http.get(config.jwks_url)
            resp.raise_for_status()
            jwks = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthTokenValidationError(f"failed to fetch JWKS: {exc}") from exc
        try:
            header = pyjwt.get_unverified_header(id_token)
            kid = header.get("kid")
            key = None
            for jwk in jwks.get("keys", []):
                if kid is None or jwk.get("kid") == kid:
                    key = pyjwt.PyJWK(jwk)
                    break
            if key is None:
                raise OAuthTokenValidationError("no matching JWKS key for id_token")
            claims: dict[str, Any] = pyjwt.decode(
                id_token,
                key=key,
                algorithms=["RS256", "ES256", "PS256"],
                audience=config.client_id,
                issuer=config.issuer,
                options={"verify_iss": config.issuer is not None},
            )
        except OAuthTokenValidationError:
            raise
        except Exception as exc:  # pyjwt raises many error types
            raise OAuthTokenValidationError(f"id_token verification failed: {exc}") from exc
        _validate_oidc_claims(claims, config, nonce, self._clock())
        return claims


class UnverifiedJWTClaimsValidator:
    """LOUD WARNING — signature is NOT verified.

    Fallback seam for environments where PyJWT is unavailable: it base64-parses
    the id_token payload WITHOUT verifying the signature, then validates
    issuer / audience / expiry / nonce claims. Because the token arrives over
    the TLS-protected token endpoint response (not from the browser), this is
    tolerable but weaker than JWKS verification. Prefer JWKSIdTokenVerifier
    whenever PyJWT is installed; do not inject this class in production unless
    you understand the trade-off.
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    async def verify(
        self,
        id_token: str,
        config: OAuthProviderConfig,
        http: httpx.AsyncClient,
        nonce: str | None,
    ) -> dict[str, Any]:
        parts = id_token.split(".")
        if len(parts) != 3:
            raise OAuthTokenValidationError("id_token is not a JWT")
        try:
            claims = json.loads(_b64url_decode(parts[1]))
        except (ValueError, json.JSONDecodeError) as exc:
            raise OAuthTokenValidationError(f"id_token payload is not valid JSON: {exc}") from exc
        if not isinstance(claims, dict):
            raise OAuthTokenValidationError("id_token payload is not an object")
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs only the provider name, never token material
        logger.warning(
            "id_token for provider %s validated WITHOUT signature verification "
            "(UnverifiedJWTClaimsValidator); install pyjwt[crypto] for JWKS verification",
            config.name,
        )
        _validate_oidc_claims(claims, config, nonce, self._clock())
        return claims


def default_id_token_verifier() -> IdTokenVerifier:
    """JWKS verification when PyJWT is importable, otherwise the loud
    claims-only fallback (a warning is logged on every use of the fallback)."""
    try:
        import jwt  # noqa: F401
    except ImportError:  # pragma: no cover - environment-dependent
        logger.warning(
            "PyJWT not installed: OIDC id_token signatures will NOT be verified "
            "(UnverifiedJWTClaimsValidator fallback)."
        )
        return UnverifiedJWTClaimsValidator()
    return JWKSIdTokenVerifier()


_STATE_TTL_SECONDS = 600.0


class OAuth2Client:
    """Authorization Code + PKCE (S256) client.

    All I/O goes through the injected ``httpx.AsyncClient``; client secrets
    come from the injected ``secret_resolver``; audit events go to the
    injected ``event_emitter`` (payloads never contain tokens).
    """

    def __init__(
        self,
        providers: dict[str, OAuthProviderConfig],
        state_store: StateStore,
        http: httpx.AsyncClient,
        secret_resolver: SecretResolver,
        id_token_verifier: IdTokenVerifier | None = None,
        event_emitter: EventEmitter | None = None,
        state_ttl_seconds: float = _STATE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._providers = dict(providers)
        # Same reason as `HomeAssistantIntegration`: a provider map can name a
        # self-hosted issuer on the operator's own network, and it arrives as a
        # constructor argument rather than through settings, so the outbound
        # policy (#155) cannot have seen it. Registering a public issuer too
        # costs nothing — an allowance is one exact origin, not a class of them.
        configure_outbound_policy(
            *(
                url
                for config in self._providers.values()
                for url in (
                    config.authorization_url,
                    config.token_url,
                    config.jwks_url or "",
                    config.userinfo_url or "",
                )
            )
        )
        self._states = state_store
        self._http = http
        self._secret_resolver = secret_resolver
        self._verifier = id_token_verifier or default_id_token_verifier()
        self._emit = event_emitter
        self._state_ttl = state_ttl_seconds
        self._clock = clock

    def _provider(self, name: str) -> OAuthProviderConfig:
        config = self._providers.get(name)
        if config is None:
            raise OAuthError(f"unknown OAuth provider: {name!r}")
        return config

    def _audit(self, event: str, **payload: Any) -> None:
        if self._emit is not None:
            self._emit(event, payload)  # payloads carry no tokens (ADR-044)

    async def authorize_url(self, provider: str, redirect_uri: str) -> tuple[str, str]:
        """Build the IdP authorization URL. Returns ``(url, state)``."""
        config = self._provider(provider)
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)  # 86 chars, within RFC 7636 43-128
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        nonce = secrets.token_urlsafe(16)
        await self._states.put(
            state,
            OAuthStateEntry(
                provider=provider,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
                nonce=nonce,
                expires_at=self._clock() + self._state_ttl,
            ),
        )
        params = httpx.QueryParams(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(config.scopes),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "nonce": nonce,
            }
        )
        sep = "&" if "?" in config.authorization_url else "?"
        return f"{config.authorization_url}{sep}{params}", state

    async def _token_post(
        self, config: OAuthProviderConfig, data: dict[str, str], *, event: str
    ) -> OAuthToken:
        secret = self._secret_resolver(config.name)
        if secret is not None:
            data["client_secret"] = secret
        try:
            resp = await self._http.post(
                config.token_url, data=data, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            self._audit("auth.oauth.failed", provider=config.name, stage=event, reason="network")
            raise OAuthExchangeError(f"token request to {config.name} failed: {exc}") from exc
        return self._parse_token_response(resp, config, event)

    def _parse_token_response(
        self, resp: httpx.Response, config: OAuthProviderConfig, event: str
    ) -> OAuthToken:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code != 200 or not isinstance(body, dict) or "error" in body:
            err = body.get("error", f"http {resp.status_code}") if isinstance(body, dict) else "?"
            self._audit("auth.oauth.failed", provider=config.name, stage=event, reason=str(err))
            raise OAuthExchangeError(f"provider {config.name} rejected {event}: {err}")
        access_token = body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            self._audit(
                "auth.oauth.failed", provider=config.name, stage=event, reason="no_access_token"
            )
            raise OAuthExchangeError(f"provider {config.name} returned no access_token")
        expires_in = body.get("expires_in")
        return OAuthToken(
            access_token=access_token,
            token_type=str(body.get("token_type", "Bearer")),
            expires_in=int(expires_in) if isinstance(expires_in, (int, float)) else None,
            refresh_token=body.get("refresh_token"),
            scope=body.get("scope"),
            id_token=body.get("id_token"),
        )

    async def exchange_code(
        self, provider: str, code: str, state: str, redirect_uri: str
    ) -> OAuthExchange:
        """Validate state, exchange the code, validate the id_token, fetch
        userinfo. Raises on any invalid input; never fabricates identity."""
        entry = await self._states.consume(state)
        if entry is None:
            self._audit("auth.oauth.failed", provider=provider, stage="state", reason="invalid")
            raise OAuthStateError("unknown, replayed, or expired OAuth state")
        if entry.provider != provider or entry.redirect_uri != redirect_uri:
            self._audit("auth.oauth.failed", provider=provider, stage="state", reason="mismatch")
            raise OAuthStateError("OAuth state does not match provider/redirect_uri")
        config = self._provider(provider)
        token = await self._token_post(
            config,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": config.client_id,
                "code_verifier": entry.code_verifier,
            },
            event="exchange",
        )
        claims: dict[str, Any] = {}
        if token.id_token is not None:
            claims = await self._verifier.verify(token.id_token, config, self._http, entry.nonce)
        userinfo = await self._fetch_userinfo(config, token)
        sub = claims.get("sub") or userinfo.get("sub") or userinfo.get("id")
        if sub is None:
            self._audit("auth.oauth.failed", provider=provider, stage="identity", reason="no_sub")
            raise OAuthExchangeError(f"provider {provider} returned no stable subject")
        merged = {**userinfo, **claims}
        identity = OAuthIdentity(
            provider=provider,
            sub=str(sub),
            email=merged.get("email"),
            email_verified=bool(merged.get("email_verified", False)),
            display_name=merged.get("name") or merged.get("preferred_username"),
        )
        self._audit("auth.oauth.login", provider=provider, sub=identity.sub)
        return OAuthExchange(identity=identity, token=token)

    async def _fetch_userinfo(
        self, config: OAuthProviderConfig, token: OAuthToken
    ) -> dict[str, Any]:
        if not config.userinfo_url:
            return {}
        try:
            resp = await self._http.get(
                config.userinfo_url,
                headers={"Authorization": f"{token.token_type} {token.access_token}"},
            )
            resp.raise_for_status()
            info = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthExchangeError(f"userinfo fetch from {config.name} failed: {exc}") from exc
        return info if isinstance(info, dict) else {}

    async def refresh(self, provider: str, refresh_token: str) -> OAuthToken:
        config = self._provider(provider)
        token = await self._token_post(
            config,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": config.client_id,
            },
            event="refresh",
        )
        self._audit("auth.oauth.refresh", provider=provider)
        return token


# --------------------------------------------------------------------------
# Phase 2 — identity linking (authN → local user)
# --------------------------------------------------------------------------


@runtime_checkable
class IdentityLinkStore(Protocol):
    """Maps the stable IdP subject ``(provider, sub)`` to a local user id.

    Email is NEVER the join key (mutable/reassignable — ADR-059)."""

    async def resolve(self, provider: str, sub: str) -> str | None: ...

    async def link(self, provider: str, sub: str, user_id: str) -> None: ...


class InMemoryIdentityLinkStore:
    def __init__(self) -> None:
        self._links: dict[tuple[str, str], str] = {}

    async def resolve(self, provider: str, sub: str) -> str | None:
        return self._links.get((provider, sub))

    async def link(self, provider: str, sub: str, user_id: str) -> None:
        self._links[(provider, sub)] = user_id


# Product-supplied provisioner: create a role="user", empty-permissions record
# and return its id. Core never creates users itself and never grants admin.
UserProvisioner = Callable[[OAuthIdentity], Awaitable[str]]


@dataclass
class IdentityLinker:
    """Linking rules per ADR-059:

    - Known ``(provider, sub)`` link → that user id.
    - Unknown identity → a new user is provisioned ONLY when
      ``open_registration`` is True and a provisioner is supplied; the
      provisioner contract is a ``role="user"`` record with empty permissions.
      Admin accounts are never created via OAuth.
    - Explicit linking of a logged-in user goes through ``link_current_user``.
    """

    store: IdentityLinkStore
    provision_user: UserProvisioner | None = None
    open_registration: bool = False
    event_emitter: EventEmitter | None = field(default=None)

    async def resolve_user(self, identity: OAuthIdentity) -> str | None:
        """Return the local user id for a verified identity, provisioning a
        role="user" account only if open registration allows it. Returns None
        when the identity is unknown and cannot be provisioned (caller must
        treat this as authentication failure — no session)."""
        user_id = await self.store.resolve(identity.provider, identity.sub)
        if user_id is not None:
            return user_id
        if not self.open_registration or self.provision_user is None:
            return None
        user_id = await self.provision_user(identity)
        await self.store.link(identity.provider, identity.sub, user_id)
        if self.event_emitter is not None:
            self.event_emitter(
                "auth.oauth.link",
                {"provider": identity.provider, "sub": identity.sub, "user_id": user_id},
            )
        return user_id

    async def link_current_user(self, identity: OAuthIdentity, user_id: str) -> None:
        """Explicit account-link performed by an already-authenticated user."""
        await self.store.link(identity.provider, identity.sub, user_id)
        if self.event_emitter is not None:
            self.event_emitter(
                "auth.oauth.link",
                {"provider": identity.provider, "sub": identity.sub, "user_id": user_id},
            )


async def begin_login(client: OAuth2Client, provider: str, redirect_uri: str) -> tuple[str, str]:
    """Start an Authorization Code + PKCE login: returns ``(url, state)``."""
    return await client.authorize_url(provider, redirect_uri)


async def complete_login(
    client: OAuth2Client,
    linker: IdentityLinker,
    *,
    provider: str,
    code: str,
    state: str,
    redirect_uri: str,
    require_verified_email: bool = False,
) -> tuple[str | None, OAuthExchange]:
    """Finish the login: exchange the code, then resolve the local user.

    Returns ``(user_id, exchange)``; ``user_id`` is ``None`` when the verified
    identity maps to no local account (and open registration cannot provision
    one) or, with ``require_verified_email``, when the IdP reports the email
    address as unverified. Raises on any invalid state/code/token.
    """
    exchange = await client.exchange_code(provider, code, state, redirect_uri)
    identity = exchange.identity
    if require_verified_email and identity.email is not None and not identity.email_verified:
        return None, exchange
    user_id = await linker.resolve_user(identity)
    return user_id, exchange
