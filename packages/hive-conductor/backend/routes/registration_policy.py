"""Registration policy endpoints and enforcement middleware (#313)."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from routes.audit import log_audit
from services.registration_policy import (
    consume_invitation,
    create_invitation,
    get_policy,
    invitation_is_valid,
    set_policy,
)

public_router = APIRouter(tags=["setup"])
admin_router = APIRouter(tags=["settings"])


class RegistrationPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["closed", "open"]


class InvitationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_seconds: int = Field(default=3600, ge=60, le=7 * 24 * 60 * 60)


@public_router.get("/registration-policy")
def registration_policy_status() -> dict[str, str]:
    """Expose only whether anonymous registration is open or closed."""
    return get_policy()


@admin_router.put("/registration-policy")
def update_registration_policy(body: RegistrationPolicyBody) -> dict[str, str]:
    result = set_policy(body.mode)
    log_audit("registration_policy_update", "admin", detail={"mode": body.mode})
    return result


@admin_router.post("/registration-invitations")
def issue_registration_invitation(body: InvitationBody) -> dict[str, str]:
    result = create_invitation(ttl_seconds=body.ttl_seconds)
    log_audit(
        "registration_invitation_create",
        "admin",
        detail={"expires_at": result["expires_at"]},
    )
    return result


class RegistrationPolicyMiddleware(BaseHTTPMiddleware):
    """Fail closed on public signup unless policy or one-time invite permits it."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "POST" or request.url.path != "/v1/auth/register":
            return await call_next(request)

        policy = get_policy()
        invite_token: str | None = None
        invite_valid = False
        if policy["mode"] != "open":
            try:
                raw = json.loads((await request.body()).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raw = {}
            if isinstance(raw, dict):
                candidate = raw.get("invite_token")
                if isinstance(candidate, str):
                    invite_token = candidate
            invite_valid = invitation_is_valid(invite_token)
            if not invite_valid:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Registration is closed."},
                )

        response = await call_next(request)
        # A rejected username/password must not burn a valid invitation. Only a
        # successful account creation consumes it, and a token is never logged.
        if invite_valid and 200 <= response.status_code < 300:
            if not consume_invitation(invite_token):
                # Another request won the one-time token between validation and
                # commit. Do not claim the second registration was authorized.
                return JSONResponse(
                    status_code=409,
                    content={"detail": "Registration invitation was already used."},
                )
        return response
