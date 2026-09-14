"""Auth provider protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class CredentialNotApplicable(Exception):
    """The presented credential does not belong to this provider's scheme."""


class AuthError(Exception):
    """The provider recognized its scheme but rejected the credential."""


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
