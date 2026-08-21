"""Backend settings — CORS origins and the Turing-internal service key.

The service key registry is seeded from TURING_SERVICE_KEY (env) so Turing's own
reactor/producers can authenticate. In dev the default key below is used; set
TURING_SERVICE_KEY in any real deployment.
"""

from __future__ import annotations

import os
from functools import lru_cache

from maistro.auth import ServiceKeyRegistry

# Dev-only default. Override with TURING_SERVICE_KEY in any real deployment.
_DEFAULT_SERVICE_KEY = "sk-svc-turing-dev-internal"

TURING_SERVICE_NAME = "turing-internal"


def cors_origins() -> list[str]:
    raw = os.environ.get("TURING_CORS_ORIGINS", "http://localhost:4321,http://127.0.0.1:4321")
    return [o.strip() for o in raw.split(",") if o.strip()]


def turing_service_key() -> str:
    return os.environ.get("TURING_SERVICE_KEY", _DEFAULT_SERVICE_KEY)


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
