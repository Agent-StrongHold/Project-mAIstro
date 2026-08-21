"""Bearer token authentication for API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from maistro.config.settings import Settings, get_settings
from maistro.security.secret_equal import secret_equal
from maistro_server.api.principal import AuthenticatedPrincipal

security_scheme = HTTPBearer(auto_error=False)


def resolve_token_principal(token: str, settings: Settings) -> AuthenticatedPrincipal | None:
    """Resolve bearer secret to principal, or None if invalid."""
    if not settings.api_keys:
        # nosec B106 — auth is DISABLED (settings.api_keys is empty), so we
        # construct a dev principal with an empty token literal. The empty
        # string is a sentinel, not a hardcoded credential.
        return AuthenticatedPrincipal(user_id="dev", token="", roles=frozenset({"admin", "user"}))  # nosec B106
    index = _build_token_index(settings)
    for secret, principal in index.items():
        if secret_equal(token, secret):
            return principal
    return None


def _build_token_index(settings: Settings) -> dict[str, AuthenticatedPrincipal]:
    """Map bearer secret -> principal. Supports ``user:secret`` entries in API_KEYS."""
    index: dict[str, AuthenticatedPrincipal] = {}
    for entry in settings.api_keys:
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry and not entry.startswith("sk-"):
            user_id, secret = entry.split(":", 1)
            roles = frozenset({"user"})
            if user_id.endswith(":admin"):
                user_id, _ = user_id.rsplit(":", 1)
                roles = frozenset({"admin", "user"})
            index[secret] = AuthenticatedPrincipal(
                user_id=user_id.strip(),
                token=secret,
                roles=roles,
            )
            index[entry] = index[secret]
        else:
            index[entry] = AuthenticatedPrincipal(
                user_id="default",
                token=entry,
                roles=frozenset({"user"}),
            )
    return index


def verify_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedPrincipal | None:
    """Verify bearer token. Returns None only when auth is disabled (no API keys)."""
    if not settings.api_keys:
        # nosec B106 — auth is DISABLED (settings.api_keys is empty), so we
        # construct a dev principal with an empty token literal. The empty
        # string is a sentinel, not a hardcoded credential.
        return AuthenticatedPrincipal(user_id="dev", token="", roles=frozenset({"admin", "user"}))  # nosec B106

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = resolve_token_principal(credentials.credentials, settings)
    if principal is not None:
        return principal

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


RequireAuth = Annotated[AuthenticatedPrincipal | None, Depends(verify_api_key)]
