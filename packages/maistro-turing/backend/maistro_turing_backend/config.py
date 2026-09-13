"""Backend settings — CORS origins and the Turing-internal service key.

The service key registry is seeded from TURING_SERVICE_KEY (env) so Turing's own
reactor/producers can authenticate. The backend refuses to start unless the key
is explicitly configured; it must never silently accept a shared public default.
"""

from __future__ import annotations

import os
from functools import lru_cache

from maistro.auth import ServiceKeyRegistry

TURING_SERVICE_NAME = "turing-internal"


def cors_origins() -> list[str]:
    raw = os.environ.get("TURING_CORS_ORIGINS", "http://localhost:4321,http://127.0.0.1:4321")
    return [o.strip() for o in raw.split(",") if o.strip()]


def turing_service_key() -> str:
    key = os.environ.get("TURING_SERVICE_KEY")
    if not key:
        raise RuntimeError("TURING_SERVICE_KEY must be set before starting the Turing backend")
    return key


@lru_cache(maxsize=1)
def build_registry() -> ServiceKeyRegistry:
    registry = ServiceKeyRegistry()
    registry.load_dict(
        {
            TURING_SERVICE_NAME: {
                "key": turing_service_key(),
                # Only the Turing-internal scopes — never admin/dashboard.
                "scopes": ["turing:*"],
            }
        }
    )
    return registry
