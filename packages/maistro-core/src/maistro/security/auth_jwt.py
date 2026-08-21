"""JWT authentication provider -- IdP-agnostic (Keycloak, Entra ID, Auth0, Okta).

Validates RS256/RS384/RS512 JWTs against a JWKS endpoint.
Extracts user identity and roles from token claims.
JWKS keys are cached with a configurable TTL.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from maistro.security._types import AuthContext, IdentityKind

logger = logging.getLogger("maistro.auth.jwt")


class JWTAuthProvider:
    """Authenticates via JWT tokens from any OIDC-compliant IdP."""

    def __init__(
        self,
        *,
        jwks_url: str,
        issuer: str,
        audience: str,
        role_claim: str = "realm_access.roles",
        kind_claim: str = "kind",
        require_org: bool = False,
        jwks_cache_ttl: int = 3600,
        jwt_decode: Any = None,
    ) -> None:
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._audience = audience
        self._role_claim = role_claim
        self._kind_claim = kind_claim
        self._require_org = require_org
        self._jwks_cache_ttl = jwks_cache_ttl
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_cache_at: float = 0.0
        self._cache_lock = asyncio.Lock()
        self._jwt_decode = jwt_decode

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        from maistro.security.auth_composite import AuthError, CredentialNotApplicable

        if not authorization:
            raise CredentialNotApplicable("Missing Authorization header")

        if not authorization.startswith("Bearer "):
            raise CredentialNotApplicable("Not a Bearer token")

        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise CredentialNotApplicable("Empty token")

        claims = await self._decode_token(token)

        user_id = claims.get("sub", "")
        username = claims.get("preferred_username", claims.get("name", user_id))
        roles = self._extract_roles(claims)

        kind_raw = self._extract_nested(claims, self._kind_claim)
        kind = IdentityKind.USER
        if kind_raw == "service_account":
            kind = IdentityKind.SERVICE_ACCOUNT
        elif kind_raw == "interactive_agent":
            kind = IdentityKind.INTERACTIVE_AGENT

        if not user_id:
            from maistro.security.auth_composite import AuthError

            raise AuthError("Token missing 'sub' claim")

        on_behalf_of = ""
        if kind == IdentityKind.INTERACTIVE_AGENT:
            obo_raw = self._extract_nested(claims, "on_behalf_of")
            on_behalf_of = str(obo_raw) if obo_raw else ""

        return AuthContext(
            user_id=str(user_id),
            username=str(username),
            roles=frozenset(str(r) for r in roles),
            kind=kind,
            auth_method="jwt",
            on_behalf_of=on_behalf_of,
        )

    async def _decode_token(self, token: str) -> dict[str, Any]:
        if self._jwt_decode is not None:
            # Test seam — MUST NOT be usable in production
            if self._jwks_url:
                raise RuntimeError(
                    "SECURITY: jwt_decode override is forbidden when jwks_url is configured. "
                    "This seam is test-only."
                )
            return dict(self._jwt_decode(token))

        try:
            import jwt as pyjwt
            from jwt import PyJWKClient
        except ImportError as err:
            msg = "PyJWT with cryptography is required: pip install PyJWT[crypto]"
            raise ImportError(msg) from err

        jwks_client = await self._get_jwks_client(pyjwt, PyJWKClient)

        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            decoded: dict[str, Any] = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512"],
                issuer=self._issuer,
                audience=self._audience,
            )
        except Exception as e:
            from maistro.security.auth_composite import AuthError

            raise AuthError(f"JWT validation failed: {e}") from e

        return decoded

    async def _get_jwks_client(self, pyjwt: Any, jwk_client_cls: type) -> Any:
        now = time.monotonic()
        if self._jwks_cache is not None and (now - self._jwks_cache_at) < self._jwks_cache_ttl:
            return self._jwks_cache

        if self._cache_lock.locked():
            if self._jwks_cache is not None:
                logger.debug("JWKS refresh in progress, using stale cache")
                return self._jwks_cache
            async with self._cache_lock:
                return self._jwks_cache or jwk_client_cls(self._jwks_url)

        async with self._cache_lock:
            now = time.monotonic()
            if self._jwks_cache is not None and (now - self._jwks_cache_at) < self._jwks_cache_ttl:
                return self._jwks_cache

            try:
                client = jwk_client_cls(self._jwks_url)
                self._jwks_cache = client
                self._jwks_cache_at = now
                logger.info("JWKS refreshed from %s", self._jwks_url)
                return client
            except Exception:
                # Fix #14: bound stale window — refuse to serve stale beyond 5x TTL
                stale_age = now - self._jwks_cache_at
                max_stale = self._jwks_cache_ttl * 5  # e.g. 5 hours if TTL is 1h
                if self._jwks_cache is not None and stale_age < max_stale:
                    logger.warning(
                        "JWKS refresh failed, serving stale (age=%.0fs, max=%.0fs)",
                        stale_age,
                        max_stale,
                    )
                    return self._jwks_cache
                logger.error("JWKS refresh failed and stale cache expired — hard-failing auth")
                raise

    def _extract_roles(self, claims: dict[str, Any]) -> list[str]:
        value = self._extract_nested(claims, self._role_claim)
        if isinstance(value, list):
            return [str(r) for r in value]
        if isinstance(value, str):
            return [value]
        return []

    @staticmethod
    def _extract_nested(claims: dict[str, Any], path: str) -> Any:
        if not path:
            return None

        # Fix #12: if path contains a dot, traverse ONLY — never flat-lookup
        # a literal dotted key, which would let attackers smuggle claims.
        if "." not in path:
            return claims.get(path)

        current: Any = claims
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
