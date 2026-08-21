"""Composite authentication provider: tries multiple providers in order.

Exception handling (fix #13):
- CredentialNotApplicable: "not my format" → try next provider
- AuthError: "valid format, rejected" → abort immediately (don't fall through)
- Other exceptions: infrastructure failure → abort (don't mask as auth miss)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from maistro.security._types import AuthContext

logger = logging.getLogger("maistro.auth.composite")


class CredentialNotApplicable(Exception):
    """Raised when a provider cannot handle this credential format at all."""


class AuthError(Exception):
    """Raised when a provider recognized the credential but rejected it."""


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
            try:
                result: AuthContext = await provider.authenticate(authorization, headers=headers)
                return result
            except CredentialNotApplicable:
                # This provider can't handle this credential type — try next
                continue
            except AuthError:
                # Provider recognized the credential but rejected it — hard fail
                raise
            except ValueError as e:
                # Legacy providers raise ValueError for both "not my format" and "rejected"
                # Treat as "not applicable" for backward compat during migration
                logger.debug("provider=%s raised ValueError: %s", type(provider).__name__, e)
                continue
            except Exception as e:
                # Infrastructure failure (JWKS down, import error, etc.) — DO NOT fall through
                logger.error(
                    "auth_provider_infrastructure_failure provider=%s error=%s",
                    type(provider).__name__,
                    e,
                )
                raise AuthError(f"Authentication infrastructure failure: {type(e).__name__}") from e

        raise AuthError("No authentication provider accepted the credentials")
