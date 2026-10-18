"""Backend settings — CORS origins and the Turing-internal service identity.

Turing has NO built-in service credential (#858). The service key registry is
seeded only from an explicitly operator-provisioned key: TURING_SERVICE_KEY
(env), or the first line of the secret file named by TURING_SERVICE_KEY_FILE
(the container-secret pattern, so rotation/revocation never touches source or
image bytes). Absent both, the backend refuses to start — Turing stays
unavailable and authenticates nobody — rather than enabling a known shared
value.

The identity's authority is expressed in the canonical maistro.auth model: the
concrete Scope values of ``ScopeCategory.TURING``, expanded by the canonical
``expand_scopes()``. No free-form wildcard string is trusted by convention, and
at registration the expanded set must equal the middleware's fixed
TURING_INTERNAL_SCOPES route allowlist — configuration drift (or a wider
operator-supplied category) fails startup instead of widening the identity.
"""

from __future__ import annotations

import logging
import os
import stat
from functools import lru_cache
from pathlib import Path

from maistro.auth import Scope, ScopeCategory, ServiceKeyRegistry, expand_scopes

from .middleware.auth import TURING_INTERNAL_SCOPES

logger = logging.getLogger("turing.config")

TURING_SERVICE_NAME = "turing-internal"


def cors_origins() -> list[str]:
    raw = os.environ.get("TURING_CORS_ORIGINS", "http://localhost:4321,http://127.0.0.1:4321")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _read_key_file(path: Path) -> str:
    """Read a file-mounted service key (first non-empty line)."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            logger.warning(
                "service key file %s is group/other readable (%o); tighten its permissions",
                path,
                mode,
            )
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"service key file {path} cannot be read: {exc}") from exc
    for line in raw.splitlines():
        key = line.strip()
        if key:
            return key
    raise RuntimeError(
        f"service key file {path} contains no key; "
        "TURING_SERVICE_KEY must be set to start the Turing backend"
    )


def turing_service_key() -> str:
    """The explicitly configured service key, or a startup failure.

    Sources, in order: TURING_SERVICE_KEY, then the file named by
    TURING_SERVICE_KEY_FILE. There is no default value and no fallback
    credential: absence raises, leaving Turing unavailable rather than
    enabled. Rotation/revocation is an env or secret-file change plus a
    restart — never a source or image change.
    """
    key = os.environ.get("TURING_SERVICE_KEY", "").strip()
    if not key:
        key_file = os.environ.get("TURING_SERVICE_KEY_FILE", "").strip()
        if key_file:
            key = _read_key_file(Path(key_file))
    if not key:
        raise RuntimeError(
            "TURING_SERVICE_KEY must be set (directly, or via TURING_SERVICE_KEY_FILE) "
            "before starting the Turing backend: without an explicitly governed "
            "service identity Turing stays unavailable and authenticates nobody"
        )
    return key


def canonical_turing_scopes() -> frozenset[Scope]:
    """The identity's authority, in the canonical permission model.

    The canonical Turing category, expanded by the canonical expander into
    concrete Scope values — the same principal/permission model every other
    service identity uses. The category string is never trusted by itself:
    build_registry() pins the result to the fixed route allowlist below.
    """
    return expand_scopes([f"{ScopeCategory.TURING.value}:*"])


@lru_cache(maxsize=1)
def build_registry() -> ServiceKeyRegistry:
    """Seed the registry with the one governed Turing service identity.

    Fails closed on: missing key material, scope drift between the canonical
    category and the route allowlist, or a registration that did not produce
    exactly that allowlist. Any of the three leaves Turing unstartable rather
    than serving a differently-scoped identity.
    """
    scopes = canonical_turing_scopes()
    if scopes != TURING_INTERNAL_SCOPES:
        drift = sorted(s.value for s in scopes ^ TURING_INTERNAL_SCOPES)
        raise RuntimeError(
            "canonical Turing category scopes drifted from the fixed "
            f"TURING_INTERNAL_SCOPES route allowlist ({drift}); refusing to "
            "mint a service identity wider than Turing's internal surface"
        )
    registry = ServiceKeyRegistry()
    registry.load_dict(
        {
            TURING_SERVICE_NAME: {
                "key": turing_service_key(),
                "scopes": sorted(s.value for s in scopes),
            }
        }
    )
    identity = registry.services.get(TURING_SERVICE_NAME)
    if identity is None or identity.scopes != TURING_INTERNAL_SCOPES:
        raise RuntimeError(
            "turing-internal service identity failed registration; refusing to start"
        )
    return registry


def service_identity_status(registry: ServiceKeyRegistry | None) -> tuple[bool, str]:
    """Readiness predicate: is a governed Turing service identity usable?

    Returns (True, service name) when the registered identity carries exactly
    the fixed internal scopes, and (False, reason) otherwise. The reason names
    configuration state only — never credential material — so it is safe to
    expose on the public readiness probe.
    """
    identity = None if registry is None else registry.services.get(TURING_SERVICE_NAME)
    if identity is None:
        return False, "turing service identity not configured"
    if identity.scopes != TURING_INTERNAL_SCOPES:
        return False, "turing service identity does not match the internal scope allowlist"
    return True, TURING_SERVICE_NAME
