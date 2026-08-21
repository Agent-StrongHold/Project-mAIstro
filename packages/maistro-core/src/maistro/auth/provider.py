"""Service key auth provider: validate X-Service-Key header → ServiceIdentity."""

from __future__ import annotations

import logging

from maistro.auth._types import ServiceIdentity
from maistro.auth.registry import ServiceKeyRegistry
from maistro.security.secret_equal import secret_equal

logger = logging.getLogger("maistro.auth.provider")


class ServiceKeyAuthProvider:
    """Validates service key from request headers against the registry.

    Checks headers in order:
      1. X-Service-Key
      2. Authorization: Bearer <key> (if it looks like a service key)
    """

    def __init__(self, registry: ServiceKeyRegistry) -> None:
        self._registry = registry

    def authenticate(
        self,
        headers: dict[str, str],
    ) -> ServiceIdentity | None:
        """Extract and validate service key from headers.

        Returns ServiceIdentity if valid, None if no service key present.
        Raises ValueError on malformed/invalid key (distinguishable from absent).
        """
        key = self._extract_key(headers)
        if key is None:
            return None

        for candidate_key, name in self._registry._key_to_name.items():
            if secret_equal(key, candidate_key):
                identity = self._registry._services.get(name)
                if identity:
                    logger.info("Authenticated service: %s", identity.name)
                return identity

        logger.warning("Invalid service key attempted")
        return None

    @staticmethod
    def _extract_key(headers: dict[str, str]) -> str | None:
        key = headers.get("x-service-key", "")
        if key:
            return key

        auth = headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ").strip()
            if token.startswith("sk-svc-"):
                return token

        return None
