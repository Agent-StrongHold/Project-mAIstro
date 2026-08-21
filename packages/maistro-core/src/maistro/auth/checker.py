"""Framework-agnostic service key auth check for non-FastAPI services.

Works with any ASGI/WSGI framework (aiohttp, starlette, etc.).
Validates X-Service-Key or Authorization: Bearer sk-svc-* headers.
"""

from __future__ import annotations

import logging

from maistro.auth._types import Scope, ServiceIdentity
from maistro.auth.provider import ServiceKeyAuthProvider
from maistro.auth.registry import ServiceKeyRegistry

logger = logging.getLogger("maistro.auth.checker")


class ServiceKeyChecker:
    """Lightweight service key validator for non-FastAPI apps.

    Usage with aiohttp:
        checker = ServiceKeyChecker.from_env()

        async def handler(request):
            identity = checker.check(request.headers)
            if identity is None:
                return web.Response(status=401, text="Invalid service key")
            ...
    """

    def __init__(self, provider: ServiceKeyAuthProvider, registry: ServiceKeyRegistry) -> None:
        self._provider = provider
        self._registry = registry

    @classmethod
    def from_env(cls) -> ServiceKeyChecker:
        registry = ServiceKeyRegistry()
        registry.load_all()
        provider = ServiceKeyAuthProvider(registry)
        issues = registry.validate()
        for issue in issues:
            logger.warning("Registry issue: %s", issue)
        logger.info("ServiceKeyChecker loaded %d services", len(registry.services))
        return cls(provider=provider, registry=registry)

    def check(self, headers: dict[str, str]) -> ServiceIdentity | None:
        """Validate service key from headers. Returns identity or None."""
        return self._provider.authenticate(headers)

    def require_scope(self, headers: dict[str, str], *scopes: Scope) -> ServiceIdentity:
        """Validate service key AND require specific scopes.

        Raises ValueError with descriptive message on failure.
        """
        identity = self._provider.authenticate(headers)
        if identity is None:
            raise ValueError("Service key required")
        missing = [s.value for s in scopes if s not in identity.scopes]
        if missing:
            raise ValueError(f"Missing scopes: {', '.join(missing)}")
        return identity

    def is_service_request(self, headers: dict[str, str]) -> bool:
        """Check if request has a service key header (without validating)."""
        key = headers.get("x-service-key", "")
        if key:
            return True
        auth = headers.get("authorization", "")
        return auth.startswith("Bearer sk-svc-")
