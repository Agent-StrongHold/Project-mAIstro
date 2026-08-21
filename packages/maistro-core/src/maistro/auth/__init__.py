"""maistro.auth — authentication plus canonical resource authorization contracts.

Long-lived service keys provide scoped permissions for cross-service communication.
Project-tree authorization is exposed separately through ``AuthorizationResolver``;
it is independent from Persona and from the legacy inline Project member-role model.
"""

from maistro.auth._types import (
    Scope,
    ScopeCategory,
    ServiceIdentity,
    expand_scopes,
)
from maistro.auth.checker import ServiceKeyChecker
from maistro.auth.client import ServiceKeyClient
from maistro.auth.provider import ServiceKeyAuthProvider
from maistro.auth.registry import ServiceKeyRegistry
from maistro.auth.resources import (
    AuthorizationDecision,
    AuthorizationResolver,
    MembershipStatus,
    Permission,
    ProjectMembership,
    ResourceKind,
    ResourceScope,
    ResourceScopeKind,
    WorkspaceMembership,
)

_OAUTH_EXPORTS = (
    "IdentityLinkStore",
    "IdentityLinker",
    "IdTokenVerifier",
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
    "default_id_token_verifier",
)


def __getattr__(name: str) -> object:
    if name in (
        "extract_service_identity",
        "require_any_scope",
        "require_scope",
        "setup_service_auth",
    ):
        from maistro.auth import middleware as _m

        return getattr(_m, name)
    if name in _OAUTH_EXPORTS:
        from maistro.auth import oauth as _o

        return getattr(_o, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AuthorizationDecision",
    "AuthorizationResolver",
    "IdTokenVerifier",
    "IdentityLinkStore",
    "IdentityLinker",
    "InMemoryIdentityLinkStore",
    "InMemoryStateStore",
    "JWKSIdTokenVerifier",
    "MembershipStatus",
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
    "Permission",
    "ProjectMembership",
    "ResourceKind",
    "ResourceScope",
    "ResourceScopeKind",
    "Scope",
    "ScopeCategory",
    "ServiceIdentity",
    "ServiceKeyAuthProvider",
    "ServiceKeyChecker",
    "ServiceKeyClient",
    "ServiceKeyRegistry",
    "StateStore",
    "UnverifiedJWTClaimsValidator",
    "WorkspaceMembership",
    "default_id_token_verifier",
    "expand_scopes",
    "extract_service_identity",
    "require_any_scope",
    "require_scope",
    "setup_service_auth",
]
