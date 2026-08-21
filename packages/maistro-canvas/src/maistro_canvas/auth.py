"""Canvas Studio standalone auth — API-key check against ``CANVAS_API_TOKEN``.

Mirrors the book-maker frontend's Express token convention
(``frontend/server/security.js``): the token is supplied either as
``Authorization: Bearer <token>`` or an ``X-Canvas-Token`` header, and the
expected value comes from the ``CANVAS_API_TOKEN`` environment variable.

Fail-closed: if ``CANVAS_API_TOKEN`` is unset the routes return 503 rather
than serving unauthenticated requests (June audit finding 3.2 — the previous
implementation accepted any key and returned an admin principal).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from fastapi import Header, HTTPException, status

from maistro.security.secret_equal import secret_equal

# Default tenant for the single-tenant standalone deployment. The
# canvas v1 routes scope every query by ``auth.org_id``; using a stable
# non-empty value keeps create/list/get consistent for one deployment.
DEFAULT_ORG_ID = "default"

TOKEN_ENV_VAR = "CANVAS_API_TOKEN"


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated principal for the standalone canvas deployment.

    Exposes attribute access (``auth.org_id``) used throughout the
    canvas v1 routes. ``org_id`` defaults to the single-tenant
    placeholder so multi-tenant code paths stay consistent until proper
    auth (Conductor Seed, DID) is wired in.
    """

    user_id: str = "default"
    org_id: str = DEFAULT_ORG_ID
    roles: tuple[str, ...] = field(default_factory=lambda: ("user",))


async def get_current_user(
    authorization: str | None = Header(None),
    x_canvas_token: str | None = Header(None),
) -> CurrentUser:
    """Validate the shared API token and return the standalone principal."""
    expected = os.environ.get(TOKEN_ENV_VAR, "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Canvas auth not configured ({TOKEN_ENV_VAR} unset)",
        )

    supplied = ""
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer":
            supplied = credentials.strip()
    if not supplied and x_canvas_token:
        supplied = x_canvas_token

    if not supplied or not secret_equal(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing canvas API token",
        )

    return CurrentUser()
