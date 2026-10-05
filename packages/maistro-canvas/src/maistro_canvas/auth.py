"""Canvas Studio standalone auth — API-key check against ``CANVAS_API_TOKEN``."""
from __future__ import annotations
import os
from fastapi import Header, HTTPException, status
from maistro.identity import Principal
from maistro.security.secret_equal import secret_equal
DEFAULT_ORG_ID = "default"
TOKEN_ENV_VAR = "CANVAS_API_TOKEN"

async def get_current_user(
    authorization: str | None = Header(None),
    x_canvas_token: str | None = Header(None),
) -> Principal:
    expected = os.environ.get(TOKEN_ENV_VAR, "")
    if not expected:
        raise HTTPException(status_code=503, detail=f"Canvas auth not configured ({TOKEN_ENV_VAR} unset)")
    supplied = ""
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer":
            supplied = credentials.strip()
    if not supplied and x_canvas_token:
        supplied = x_canvas_token
    if not supplied or not secret_equal(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing canvas API token")
    return Principal(user_id="default", org_id=DEFAULT_ORG_ID, roles=frozenset({"user"}))
