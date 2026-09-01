"""Microsoft Entra ID specialization for canonical OAuth user authentication.

Entra remains an external authentication source only.  MAIstro keeps its own
canonical user/session/authorization model.  The durable external account key
is the immutable Entra pair ``(tid, oid)`` rather than email, UPN, display name,
or the pairwise OIDC ``sub`` claim.

The generic :mod:`maistro.auth.oauth` client still owns Authorization Code +
PKCE, state/nonce validation, token exchange, and JWKS signature verification.
This module contributes only Microsoft-specific provider metadata and verified
identity normalization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from maistro.auth.oauth import (
    IdTokenVerifier,
    JWKSIdTokenVerifier,
    OAuthProviderConfig,
    OAuthTokenValidationError,
)

ENTRA_PROVIDER_NAME = "entra"
_ENTRA_LOGIN_ORIGIN = "https://login.microsoftonline.com"
_DEFAULT_SCOPES = ("openid", "profile", "email")


@dataclass(frozen=True)
class EntraIdentityKey:
    """Canonical immutable external identity for one Entra directory user."""

    tenant_id: str
    object_id: str

    @property
    def subject(self) -> str:
        """Injective string representation usable by the generic link store."""
        return f"{self.tenant_id}:{self.object_id}"

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> EntraIdentityKey:
        return cls(
            tenant_id=_canonical_uuid_claim(claims.get("tid"), "tid"),
            object_id=_canonical_uuid_claim(claims.get("oid"), "oid"),
        )

    @classmethod
    def parse_subject(cls, subject: str) -> EntraIdentityKey:
        """Recover the structured ``(tid, oid)`` pair from a stored subject."""
        parts = subject.split(":")
        if len(parts) != 2:
            raise ValueError("Entra subject must encode exactly tid:oid")
        return cls(
            tenant_id=_canonical_uuid_claim(parts[0], "tid"),
            object_id=_canonical_uuid_claim(parts[1], "oid"),
        )


def _canonical_uuid_claim(value: object, claim: str) -> str:
    if not isinstance(value, str) or not value:
        raise OAuthTokenValidationError(f"Entra id_token has no valid {claim} claim")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise OAuthTokenValidationError(
            f"Entra id_token has no valid {claim} claim"
        ) from exc
    # Entra directory/object identifiers are UUIDs.  Canonical lowercase text
    # prevents alternate spellings from creating duplicate durable links.
    return str(parsed)


def canonical_entra_tenant_id(tenant_id: str) -> str:
    """Validate a deployment's tenant as one concrete Entra directory UUID.

    ``common``, ``organizations`` and other multi-tenant aliases are rejected on
    purpose: #491 requires explicit tenant admission, not runtime tenant choice.
    """
    try:
        return str(UUID(tenant_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Entra tenant_id must be one concrete directory UUID") from exc


def build_entra_provider_config(
    *,
    tenant_id: str,
    client_id: str,
    scopes: tuple[str, ...] = _DEFAULT_SCOPES,
    name: str = ENTRA_PROVIDER_NAME,
) -> OAuthProviderConfig:
    """Build the tenant-specific Entra v2 OIDC provider configuration."""
    tenant = canonical_entra_tenant_id(tenant_id)
    client = client_id.strip()
    if not client:
        raise ValueError("Entra client_id must not be blank")
    if "openid" not in scopes:
        raise ValueError("Entra scopes must include openid")

    tenant_base = f"{_ENTRA_LOGIN_ORIGIN}/{tenant}"
    return OAuthProviderConfig(
        name=name,
        authorization_url=f"{tenant_base}/oauth2/v2.0/authorize",
        token_url=f"{tenant_base}/oauth2/v2.0/token",
        client_id=client,
        jwks_url=f"{tenant_base}/discovery/v2.0/keys",
        # The tenant-specific v2 issuer is intentionally fixed.  A token from a
        # different tenant therefore fails generic issuer validation before the
        # Entra-specific tid/oid checks below.
        issuer=f"{tenant_base}/v2.0",
        # Human identity is available in the signed id_token.  Avoid a second
        # Graph/UserInfo request and its extra bearer-token exposure.
        userinfo_url=None,
        scopes=scopes,
        require_id_token=True,
    )


class EntraIdTokenVerifier:
    """JWKS verifier that normalizes verified Entra ``tid`` + ``oid`` identity.

    The delegate verifies signature, issuer, audience, expiry, nonce and the
    ordinary OIDC subject first.  Only then do we inspect Microsoft claims.
    The returned ``sub`` is replaced by the injective canonical ``tid:oid`` key
    so the existing ``IdentityLinkStore(provider, sub)`` persists exactly the
    external identity #491 requires without making the generic store Entra-aware.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        delegate: IdTokenVerifier | None = None,
    ) -> None:
        self._tenant_id = canonical_entra_tenant_id(tenant_id)
        self._delegate = delegate or JWKSIdTokenVerifier()

    async def verify(
        self,
        id_token: str,
        config: OAuthProviderConfig,
        http: httpx.AsyncClient,
        nonce: str | None,
    ) -> dict[str, Any]:
        claims = await self._delegate.verify(id_token, config, http, nonce)
        identity = EntraIdentityKey.from_claims(claims)
        if identity.tenant_id != self._tenant_id:
            raise OAuthTokenValidationError("Entra id_token tenant is not admitted")

        normalized = dict(claims)
        normalized["sub"] = identity.subject
        return normalized


__all__ = [
    "ENTRA_PROVIDER_NAME",
    "EntraIdTokenVerifier",
    "EntraIdentityKey",
    "build_entra_provider_config",
    "canonical_entra_tenant_id",
]
