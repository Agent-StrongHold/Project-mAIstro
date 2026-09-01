"""Registration policy endpoints and enforcement middleware (#313)."""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from services.registration_policy import (
    claim_invitation,
    create_invitation,
    get_policy,
    restore_invitation,
    set_policy,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from routes.audit import log_audit

public_router = APIRouter(tags=["setup"])
admin_router = APIRouter(tags=["settings"])
_SETUP_COMPLETE_LOCK = asyncio.Lock()


class RegistrationPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["closed", "open"]


class InvitationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_seconds: int = Field(default=3600, ge=60, le=7 * 24 * 60 * 60)


def _audit_actor(request: Request) -> str:
    """Return the authenticated principal's stable identifier for audit entries."""
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        actor = user.get("id") or user.get("username")
        if actor:
            return str(actor)
    return "unknown"


@public_router.get("/registration-policy")
def registration_policy_status() -> dict[str, str]:
    """Expose only whether anonymous registration is open or closed."""
    return get_policy()


@admin_router.put("/registration-policy")
def update_registration_policy(
    body: RegistrationPolicyBody, request: Request
) -> dict[str, str]:
    result = set_policy(body.mode)
    log_audit(
        "registration_policy_update",
        _audit_actor(request),
        detail={"mode": body.mode},
    )
    return result


@admin_router.post("/registration-invitations")
def issue_registration_invitation(body: InvitationBody, request: Request) -> dict[str, str]:
    result = create_invitation(ttl_seconds=body.ttl_seconds)
    log_audit(
        "registration_invitation_create",
        _audit_actor(request),
        detail={"expires_at": result["expires_at"]},
    )
    return result


def _invite_token_from_request_body(raw_body: bytes) -> str | None:
    try:
        raw = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    candidate = raw.get("invite_token")
    return candidate if isinstance(candidate, str) else None


class RegistrationPolicyMiddleware(BaseHTTPMiddleware):
    """Enforce one-shot setup and fail-closed post-setup registration."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "POST" and request.url.path == "/v1/setup/complete":
            # The route itself re-checks durable setup state. Serializing the
            # check+commit window means concurrent first-run requests cannot
            # both pass that check and overwrite the owner credentials.
            async with _SETUP_COMPLETE_LOCK:
                return await call_next(request)

        if request.method != "POST" or request.url.path != "/v1/auth/register":
            return await call_next(request)

        policy = get_policy()
        # A supplied invitation is a one-time capability even while ordinary
        # registration is open. Claim it whenever it is valid so an operator
        # cannot later close registration and discover that the same link still
        # creates another account. An invalid/missing token is harmless while
        # policy is open, but is not enough to cross a closed policy.
        invite_token = _invite_token_from_request_body(await request.body())
        claimed = claim_invitation(invite_token) if invite_token else None
        if policy["mode"] != "open" and claimed is None:
            return JSONResponse(
                status_code=403,
                content={"detail": "Registration is closed."},
            )

        response = await call_next(request)
        # Claim before account creation, restore only when the account creator
        # rejects the request. This prevents two concurrent requests from both
        # committing users with one invitation inside a process/store instance.
        if claimed is not None and not (200 <= response.status_code < 300):
            restore_invitation(invite_token, claimed)
        return response
