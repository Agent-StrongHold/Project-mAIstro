"""Product-level Microsoft Entra specialization for the generic OAuth service.

The core OAuth client remains provider-agnostic.  Hive selects this verifier at
the product boundary so a provider named ``entra`` receives Microsoft-specific
configuration and immutable ``tid``/``oid`` checks, while every other OIDC
provider continues through the ordinary JWKS verifier unchanged.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

import httpx

from maistro.auth.entra import ENTRA_PROVIDER_NAME, EntraIdTokenVerifier
from maistro.auth.oauth import (
    IdTokenVerifier,
    JWKSIdTokenVerifier,
    OAuthProviderConfig,
    OAuthTokenValidationError,
)

_ENTRA_HOST = "login.microsoftonline.com"


def entra_tenant_from_provider_config(config: OAuthProviderConfig) -> str:
    """Validate that an ``entra`` provider is one tenant-specific v2 config."""
    if config.name != ENTRA_PROVIDER_NAME:
        raise ValueError("provider is not the Entra specialization")
    if config.issuer is None:
        raise OAuthTokenValidationError("Entra provider requires a tenant-specific issuer")

    parsed = urlsplit(config.issuer)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _ENTRA_HOST
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OAuthTokenValidationError("Entra issuer is not a Microsoft tenant v2 issuer")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[1] != "v2.0":
        raise OAuthTokenValidationError("Entra issuer must identify one concrete v2 tenant")
    try:
        tenant_id = str(UUID(parts[0]))
    except ValueError as exc:
        raise OAuthTokenValidationError("Entra issuer tenant must be a directory UUID") from exc

    base = f"https://{_ENTRA_HOST}/{tenant_id}"
    expected = {
        "authorization_url": f"{base}/oauth2/v2.0/authorize",
        "token_url": f"{base}/oauth2/v2.0/token",
        "jwks_url": f"{base}/discovery/v2.0/keys",
        "issuer": f"{base}/v2.0",
    }
    actual = {
        "authorization_url": config.authorization_url,
        "token_url": config.token_url,
        "jwks_url": config.jwks_url,
        "issuer": config.issuer,
    }
    if actual != expected:
        raise OAuthTokenValidationError(
            "Entra provider endpoints must all belong to the configured tenant"
        )
    if config.userinfo_url is not None:
        raise OAuthTokenValidationError(
            "Entra human login must derive identity from the verified id_token"
        )
    if not config.require_id_token or "openid" not in config.scopes:
        raise OAuthTokenValidationError("Entra human login requires an OIDC id_token")
    return tenant_id


class ProductIdTokenVerifier:
    """Dispatch Microsoft Entra claims without changing the generic OAuth core."""

    def __init__(self, generic: IdTokenVerifier | None = None) -> None:
        self._generic = generic or JWKSIdTokenVerifier()

    async def verify(
        self,
        id_token: str,
        config: OAuthProviderConfig,
        http: httpx.AsyncClient,
        nonce: str | None,
    ) -> dict[str, object]:
        if config.name != ENTRA_PROVIDER_NAME:
            return await self._generic.verify(id_token, config, http, nonce)

        tenant_id = entra_tenant_from_provider_config(config)
        verifier = EntraIdTokenVerifier(tenant_id=tenant_id, delegate=self._generic)
        return await verifier.verify(id_token, config, http, nonce)


__all__ = ["ProductIdTokenVerifier", "entra_tenant_from_provider_config"]
