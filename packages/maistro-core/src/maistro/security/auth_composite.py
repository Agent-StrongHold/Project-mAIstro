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

if TYPE_CHECKING:
    from maistro.security._types import AuthContext

logger = logging.getLogger("maistro.auth.composite")


def _provider_scheme(provider: Any) -> str:
    """Return a bounded scheme label suitable for audit logs."""
    scheme = getattr(provider, "scheme", None)
    if isinstance(scheme, str) and scheme:
        return scheme
    return type(provider).__name__


class CredentialNotApplicable(Exception):
    """Raised when a provider cannot recognize this credential scheme."""


class AuthError(Exception):
    """Raised when a provider recognized the scheme but rejected the credential."""


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
            except AuthError as error:
                # Recognition is terminal: an invalid credential must not be
                # reinterpreted by a later provider.
                logger.info(
                    "auth_provider_rejected scheme=%s error_type=%s",
                    scheme,
                    type(error).__name__,
                )
                raise
            except Exception as error:
                # Infrastructure failure (JWKS down, import error, etc.) — DO NOT fall through.
                logger.error(
                    "auth_provider_infrastructure_failure scheme=%s error_type=%s",
                    scheme,
                    type(error).__name__,
                )
                raise AuthError(
                    f"Authentication infrastructure failure: {type(error).__name__}"
                ) from error

        raise AuthError("No authentication provider accepted the credentials")
