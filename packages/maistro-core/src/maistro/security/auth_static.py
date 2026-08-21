"""Static API key authentication provider.

Authenticates service-to-service calls via a shared static key.
Returns SYSTEM_AUTH identity — no user impersonation from headers.
"""

from __future__ import annotations

import hmac

from maistro.security._types import SYSTEM_AUTH, AuthContext, IdentityKind


class StaticKeyAuthProvider:
    """Authenticates via static API key. Returns system identity only."""

    def __init__(self, api_key: str, read_only: bool = False) -> None:
        self._api_key = api_key
        self._read_only = read_only

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        if not authorization:
            msg = "Missing Authorization header"
            raise ValueError(msg)

        if not authorization.startswith("Bearer "):
            msg = "Invalid authorization format"
            raise ValueError(msg)

        token = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(token, self._api_key):
            msg = "Invalid API key"
            raise ValueError(msg)

        if self._read_only:
            return AuthContext(
                user_id="system",
                username="system",
                roles=frozenset({"user"}),
                kind=IdentityKind.SYSTEM,
                auth_method="api_key",
            )

        return SYSTEM_AUTH
