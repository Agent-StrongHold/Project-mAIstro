"""Auth provider protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class CredentialNotApplicable(Exception):
    """The presented credential does not belong to this provider's scheme."""


class AuthError(Exception):
    """The provider recognized its scheme but rejected the credential."""


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Return a Bearer credential, or ``None`` for another auth scheme.

    An empty string means the Bearer scheme was present without a credential;
    callers must reject that as an invalid recognized credential rather than
    treating it as an opportunity for another provider.
    """
    if not authorization:
        return None

    parts = authorization.split(None, 1)
    if not parts or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() if len(parts) == 2 else ""


@runtime_checkable
class AuthProvider(Protocol):
    """Authenticates requests and returns auth context.

    Providers raise ``CredentialNotApplicable`` only when the presented
    credential is not their scheme. Once a provider recognizes its scheme, a
    failed verification raises ``AuthError`` so a composite cannot reinterpret
    the credential through another provider. These exceptions are defined here,
    at the provider contract boundary, rather than by the composite
    implementation so individual providers do not depend on their consumer.
    """

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Returns auth context on success, raises AuthError on failure."""
        ...
