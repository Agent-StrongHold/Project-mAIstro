"""Auth provider protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    """Authenticates requests and returns auth context."""

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Returns auth context on success, raises AuthError on failure."""
        ...
