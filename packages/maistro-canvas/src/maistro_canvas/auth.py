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

from fastapi import Header, HTTPException, status

from maistro.identity import Principal
from maistro.security.secret_equal import secret_equal

# Default tenant for the single-tenant standalone deployment. The
# canvas v1 routes scope every query by ``auth.org_id``; using a stable
# non-empty value keeps create/list/get consistent for one deployment.
DEFAULT_ORG_ID = "default"

TOKEN_ENV_VAR = "CANVAS_API_TOKEN"


async def get_current_user(
    authorization: str | None = Header(None),
    x_canvas_token: str | None = Header(None),
) -> Principal:
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

    return Principal(
        user_id="default",
        org_id=DEFAULT_ORG_ID,
        roles=frozenset({"user"}),
    )


def scope_org_id(principal: Principal) -> str:
    """Non-optional org scope for canvas stores (single-tenant default)."""
    return principal.org_id or DEFAULT_ORG_ID
