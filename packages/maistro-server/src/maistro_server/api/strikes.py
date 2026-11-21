"""Admin strike-recovery surface over Container.strike_recovery (#2315).

Reads the Container-wired ``StrikeRecoveryService`` so construction is no
longer an unread second reference. Chat/tool paths record strikes via Gate;
unlock / enable / remove-strikes remain an admin-only HTTP surface.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from maistro.security.sentinel.authz_types import Principal
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal

router = APIRouter(tags=["strikes"])

Operation = Literal["unlock", "enable", "remove_strikes"]


class StrikeRecoverBody(BaseModel):
    """Optional body for remove-strikes; unlock/enable ignore ``count``."""

    count: int | None = Field(default=None, ge=1, description="Strikes to remove")


class StrikeRecordView(BaseModel):
    user_id: str
    strike_count: int
    is_locked: bool
    disabled: bool


def _acting_principal(auth: AuthenticatedPrincipal) -> Principal:
    return Principal(id=auth.user_id, kind="human", roles=tuple(sorted(auth.roles)))


def _require_admin(auth: AuthenticatedPrincipal) -> None:
    if not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required for strike recovery",
        )


def _recovery_service(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="container not ready",
        )
    # Direct attribute read — wiring-reads ratchet requires a production reader
    # of Container.strike_recovery (#2315 / #1172).
    service = container.strike_recovery
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="strike recovery is not configured (no strike tracker)",
        )
    return service


def _view(record: Any, *, user_id: str) -> StrikeRecordView:
    if record is None:
        return StrikeRecordView(user_id=user_id, strike_count=0, is_locked=False, disabled=False)
    return StrikeRecordView(
        user_id=user_id,
        strike_count=int(getattr(record, "strike_count", 0)),
        is_locked=bool(getattr(record, "is_locked", False)),
        disabled=bool(getattr(record, "disabled", False)),
    )


async def _recover(
    request: Request,
    auth: AuthenticatedPrincipal,
    *,
    target_user_id: str,
    operation: Operation,
    count: int | None = None,
) -> StrikeRecordView:
    _require_admin(auth)
    service = _recovery_service(request)
    actor = _acting_principal(auth)
    if operation == "unlock":
        record = await service.unlock(actor, target_user_id)
    elif operation == "enable":
        record = await service.enable(actor, target_user_id)
    else:
        record = await service.remove_strikes(actor, target_user_id, count=count)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"strike recovery {operation} denied",
        )
    return _view(record, user_id=target_user_id)


@router.post(
    "/admin/strikes/{target_user_id}/unlock",
    response_model=StrikeRecordView,
)
async def unlock_strikes(
    target_user_id: str,
    request: Request,
    auth: RequireAuth,
) -> StrikeRecordView:
    if auth is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    return await _recover(request, auth, target_user_id=target_user_id, operation="unlock")


@router.post(
    "/admin/strikes/{target_user_id}/enable",
    response_model=StrikeRecordView,
)
async def enable_strikes(
    target_user_id: str,
    request: Request,
    auth: RequireAuth,
) -> StrikeRecordView:
    if auth is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    return await _recover(request, auth, target_user_id=target_user_id, operation="enable")


@router.post(
    "/admin/strikes/{target_user_id}/remove",
    response_model=StrikeRecordView,
)
async def remove_strikes(
    target_user_id: str,
    request: Request,
    auth: RequireAuth,
    body: StrikeRecoverBody | None = None,
) -> StrikeRecordView:
    if auth is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    count = body.count if body is not None else None
    return await _recover(
        request,
        auth,
        target_user_id=target_user_id,
        operation="remove_strikes",
        count=count,
    )
