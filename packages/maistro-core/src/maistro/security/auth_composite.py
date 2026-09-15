"""Experimental composite authentication provider: tries providers in order.

This provider family is currently not wired into a shipped service. Keep that
boundary explicit until every provider implements the distinction below.

Exception handling (fix #13, #1190):
- CredentialNotApplicable: "not my format" -> try next provider
- AuthError: "recognized format, rejected" -> abort immediately
- Other exceptions: infrastructure failure -> abort (don't mask as auth miss)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from maistro.protocols.auth import AuthError, CredentialNotApplicable

if TYPE_CHECKING:
    from maistro.security._types import AuthContext

logger = logging.getLogger("maistro.auth.composite")


def _provider_scheme(provider: Any) -> str:
    """Return a trusted scheme label for credential-free audit records.

    Provider instances and classes are not trusted configuration: a provider
    implementation can expose a mutable ``scheme`` attribute, and a dynamic
    class name can contain request data. Only the built-in provider types get
    labels here; unknown implementations use a constant safe label rather than
    echoing metadata into logs.
    """
    # Keep this import local so the experimental composite does not become an
    # import dependency of the individual providers.
    from maistro.security.auth_cookie import CookieAuthProvider
    from maistro.security.auth_demo_cookie import DemoCookieAuthProvider
    from maistro.security.auth_jwt import JWTAuthProvider
    from maistro.security.auth_static import StaticKeyAuthProvider

    built_in_schemes = {
        StaticKeyAuthProvider: "static_api_key",
        JWTAuthProvider: "jwt_bearer",
        CookieAuthProvider: "session_cookie",
        DemoCookieAuthProvider: "demo_session",
    }
    return built_in_schemes.get(type(provider), "custom_provider")


class CompositeAuthProvider:
    """Tries multiple auth providers in order. First success wins.

    - CredentialNotApplicable → skip to next provider
    - AuthError → stop, propagate (credential was recognized but invalid)
    - Any other exception → stop, propagate (infrastructure failure, not an auth miss)
    """

    def __init__(self, providers: list[Any]) -> None:
        self._providers = providers

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        for provider in self._providers:
            scheme = _provider_scheme(provider)
            try:
                result: AuthContext = await provider.authenticate(authorization, headers=headers)
                # This is audit evidence about the scheme, never the credential.
                logger.info("auth_provider_accepted scheme=%s", scheme)
                return result
            except CredentialNotApplicable:
                logger.info("auth_provider_not_applicable scheme=%s", scheme)
                continue
            except AuthError:
                # Recognition is terminal: an invalid credential must not be
                # reinterpreted by a later provider. Keep audit fields finite
                # and credential-free; provider exception metadata is untrusted.
                logger.info("auth_provider_rejected scheme=%s", scheme)
                raise
            except Exception as error:
                # Infrastructure failure (JWKS down, import error, etc.) — DO NOT fall through.
                # Do not expose arbitrary provider exception metadata in logs or errors.
                logger.error("auth_provider_infrastructure_failure scheme=%s", scheme)
                raise AuthError("Authentication infrastructure failure") from error

        raise AuthError("No authentication provider accepted the credentials")
