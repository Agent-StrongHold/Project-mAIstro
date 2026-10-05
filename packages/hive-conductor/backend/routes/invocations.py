"""Evidence-backed operator recovery of ambiguous canonical Invocations (#1118)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from middleware.invocation_ingress import MAX_RESOLUTION_BYTES
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from services.request_principal import require_principal
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from maistro.capabilities.invocation import (
    Invocation,
    InvocationUsage,
    ReconciliationDisposition,
    StaleInvocationUpdate,
    UnsafeEffectRetry,
)
from maistro.capabilities.operator_reconciliation import (
    INVOCATIONS_INSPECT,
    INVOCATIONS_RECONCILE,
    InvocationNotVisible,
    OperatorInvocationReconciliation,
)
from maistro.quota.invocation_quota import measured_usage_amounts
from maistro.security.redact import redact_structure


class InvocationRoute(APIRoute):
    """Bound evidence before JSON parsing and keep rejected inputs out of errors."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        received = 0

        async def bounded_receive() -> Any:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_RESOLUTION_BYTES:
                    raise HTTPException(413, "reconciliation request exceeds 64 KiB")
            return message

        await super().handle(scope, bounded_receive, send)

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def validated(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # FastAPI's default includes the rejected body as `input`.
                # A credential-bearing evidence rejection must not echo it.
                raise HTTPException(422, "Invalid reconciliation request") from exc

        return validated


router = APIRouter(tags=["invocations"], route_class=InvocationRoute)


def _operator_actor(request: Request, permission: str) -> str:
    principal = require_principal(request)
    if not principal.has_permission(permission):
        raise HTTPException(403, "Invocation permission required")
    return principal.actor_id()


def operator_service() -> OperatorInvocationReconciliation:
    from services.dag_agents import _container

    container = _container()
    if container is None or container.capability_effects is None:
        raise HTTPException(503, "canonical Invocation authority unavailable")
    return OperatorInvocationReconciliation(
        container.capability_effects, container.workspace_store, container.project_scope_store
    )


def _view(item: Invocation) -> dict[str, Any]:
    """Expose correlation and evidence, never provider config or request credentials."""
    view = item.model_dump(mode="json", exclude={"binding", "request"})
    view.update(
        binding_id=item.binding.binding_id,
        capability=item.binding.capability,
        provider=item.binding.provider_name,
    )
    return dict(redact_structure(view))


class ResolutionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # The installed API negotiator owns this selector; it is never effect evidence.
    api_version: Any | None = Field(default=None, exclude=True)

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    expected_revision: StrictInt = Field(ge=0)
    disposition: ReconciliationDisposition
    reason: str = Field(min_length=1, max_length=2000)
    evidence: dict[str, Any] | None = None
    result: Any | None = None
    usage: InvocationUsage | None = None
    stale_before: datetime | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> ResolutionBody:
        if self.disposition is not ReconciliationDisposition.INDETERMINATE and not self.evidence:
            raise ValueError("applied/not_applied resolution requires nonempty evidence")
        if self.disposition is not ReconciliationDisposition.APPLIED and (
            self.result is not None or self.usage is not None
        ):
            raise ValueError("result and usage require an applied disposition")
        if self.stale_before is not None and (
            self.stale_before.utcoffset() is None or self.stale_before > datetime.now(UTC)
        ):
            raise ValueError("stale_before must be a past timestamp with a timezone")
        # Pydantic's JSON-mode dump already maps nonfinite Any values to null.
        # Check the unconverted evidence first so accepted bytes stay truthful.
        json.dumps((self.evidence, self.result), allow_nan=False)
        payload = self.model_dump(mode="json")
        if len(json.dumps(payload, allow_nan=False).encode()) > MAX_RESOLUTION_BYTES:
            raise ValueError("resolution evidence exceeds 64 KiB")
        measured_usage_amounts(self.usage)
        if redact_structure(payload) != payload:
            raise ValueError("remove credentials from resolution evidence")
        return self


@router.get("")
async def discover_invocations(
    request: Request,
    workspace_id: Annotated[str, Query(min_length=1)],
    project_id: Annotated[str, Query(min_length=1)],
    stale_before: datetime,
    service: Annotated[OperatorInvocationReconciliation, Depends(operator_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    after_created_at: datetime | None = None,
    after_invocation_id: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
) -> dict[str, Any]:
    actor = _operator_actor(request, INVOCATIONS_INSPECT)
    if (after_created_at is None) != (after_invocation_id is None):
        raise HTTPException(422, "Supply both cursor fields together")
    after = (
        (after_created_at, after_invocation_id)
        if after_created_at is not None and after_invocation_id is not None
        else None
    )
    try:
        items = await service.discover(
            principal_id=actor,
            workspace_id=workspace_id,
            project_id=project_id,
            stale_before=stale_before,
            limit=limit + 1,
            after=after,
        )
    except InvocationNotVisible as exc:
        raise HTTPException(404, "Invocation not found") from exc
    except RuntimeError as exc:
        raise HTTPException(503, "bounded scoped Invocation discovery unavailable") from exc
    page = items[:limit]
    next_cursor = None
    if len(items) > limit:
        next_cursor = {
            "after_created_at": page[-1].created_at.isoformat(),
            "after_invocation_id": page[-1].invocation_id,
        }
    return {"items": [_view(item) for item in page], "next_cursor": next_cursor}


@router.get("/{invocation_id}")
async def inspect_invocation(
    invocation_id: str,
    request: Request,
    workspace_id: Annotated[str, Query(min_length=1)],
    project_id: Annotated[str, Query(min_length=1)],
    service: Annotated[OperatorInvocationReconciliation, Depends(operator_service)],
) -> dict[str, Any]:
    try:
        item = await service.get(
            invocation_id,
            principal_id=_operator_actor(request, INVOCATIONS_INSPECT),
            workspace_id=workspace_id,
            project_id=project_id,
        )
    except InvocationNotVisible as exc:
        raise HTTPException(404, "Invocation not found") from exc
    return _view(item)


@router.post("/{invocation_id}/reconcile")
async def reconcile_invocation(
    invocation_id: str,
    body: ResolutionBody,
    request: Request,
    service: Annotated[OperatorInvocationReconciliation, Depends(operator_service)],
) -> dict[str, Any]:
    actor = _operator_actor(request, INVOCATIONS_RECONCILE)
    try:
        existing = await service.get(
            invocation_id,
            principal_id=actor,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            permission=INVOCATIONS_RECONCILE,
        )
    except InvocationNotVisible as exc:
        raise HTTPException(404, "Invocation not found") from exc
    if body.disposition is ReconciliationDisposition.APPLIED:
        try:
            measured_usage_amounts(body.usage if body.usage is not None else existing.usage)
        except ValueError as exc:
            raise HTTPException(
                422, "Reconciliation requires representable usage evidence"
            ) from exc
    try:
        settled = await service.effects.invocations.reconcile(
            invocation_id,
            source="operator-api",
            actor=actor,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            expected_revision=body.expected_revision,
            disposition=body.disposition,
            reason=body.reason,
            evidence=body.evidence,
            result=body.result,
            usage=body.usage,
            stale_before=body.stale_before,
        )
    except (StaleInvocationUpdate, UnsafeEffectRetry) as exc:
        raise HTTPException(
            409, "Invocation changed or is still active; inspect before retrying"
        ) from exc
    except Exception as exc:
        raise HTTPException(
            503, "Reconciliation may have been recorded; inspect its revision before retrying"
        ) from exc
    return _view(settled)
