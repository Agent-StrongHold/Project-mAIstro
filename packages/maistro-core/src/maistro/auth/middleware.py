"""FastAPI middleware for service key auth and scope enforcement."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request

from maistro.auth._types import Scope, ServiceIdentity
from maistro.auth.provider import ServiceKeyAuthProvider
from maistro.auth.registry import ServiceKeyRegistry

logger = logging.getLogger("maistro.auth.middleware")

_SERVICE_IDENTITY_KEY = "service_identity"


def setup_service_auth(registry: ServiceKeyRegistry) -> ServiceKeyAuthProvider:
    """Create and return a configured auth provider. Call once at app startup."""
    provider = ServiceKeyAuthProvider(registry)
    issues = registry.validate()
    for issue in issues:
        logger.warning("Registry issue: %s", issue)
    return provider


async def extract_service_identity(
    request: Request,
    provider: ServiceKeyAuthProvider | None = None,
) -> ServiceIdentity | None:
    """FastAPI dependency: extract service identity from request if present.

    Returns None if no service key in headers (regular user request).
    Raises 401 if service key is present but invalid.
    """
    if provider is None:
        return None

    headers = dict(request.headers)
    identity = provider.authenticate(headers)
    if identity is not None:
        request.state.service_identity = identity
        return identity

    key = headers.get("x-service-key", "") or (
        headers.get("authorization", "").startswith("Bearer sk-svc-")
        and headers.get("authorization", "")
    )
    if key:
        raise HTTPException(status_code=401, detail="Invalid service key")

    return None


def require_scope(*required_scopes: Scope) -> Any:
    """FastAPI dependency factory: require one or more scopes.

    Usage:
        @app.post("/v1/chat/completions")
        async def chat(identity: ServiceIdentity = Depends(require_scope(Scope.CHAT_COMPLETIONS))):
            ...
    """

    async def _check(request: Request) -> ServiceIdentity:
        identity: ServiceIdentity | None = getattr(request.state, _SERVICE_IDENTITY_KEY, None)
        if identity is None:
            raise HTTPException(
                status_code=403,
                detail="Service authentication required",
            )
        missing = [s.value for s in required_scopes if not identity.has_scope(s)]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing scopes: {', '.join(missing)}",
            )
        return identity

    return _check


def require_any_scope(*required_scopes: Scope) -> Any:
    """FastAPI dependency: require at least one of the given scopes."""

    async def _check(request: Request) -> ServiceIdentity:
        identity: ServiceIdentity | None = getattr(request.state, _SERVICE_IDENTITY_KEY, None)
        if identity is None:
            raise HTTPException(
                status_code=403,
                detail="Service authentication required",
            )
        if not identity.has_any_scope(*required_scopes):
            scope_names = ", ".join(s.value for s in required_scopes)
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {scope_names}",
            )
        return identity

    return _check
