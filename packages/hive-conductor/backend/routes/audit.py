from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from services.audit_query import (
    DEFAULT_AUDIT_PAGE_SIZE,
    AuditPage,
    actor_of,
    iter_export_entries,
    page_entries,
    retention,
)

router = APIRouter(tags=["audit"])

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    action: str
    actor: str
    target: str | None = None
    detail: dict[str, Any] = {}
    severity: Literal["info", "warning", "critical"] = "info"
    created_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def log_audit(
    action: str,
    actor: str,
    target: str | None = None,
    detail: dict | None = None,
    severity: Literal["info", "warning", "critical"] = "info",
) -> None:
    entry_id = str(uuid4())
    entry = AuditEntry(
        id=entry_id,
        action=action,
        actor=actor,
        target=target,
        detail=detail or {},
        severity=severity,
        created_at=_now(),
    )
    stores.audit_log[entry_id] = entry.model_dump(mode="json")


def _principal(request: Request) -> dict[str, Any]:
    """The authenticated principal, or a fail-closed 401.

    AuthMiddleware sets `request.state.user` on every /v1/ path; a handler
    that cannot name its principal must refuse rather than guess, because the
    answer below is scoped to that principal (#1174's rule, applied here).
    """
    user = getattr(request.state, "user", None) or {}
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _actor_scope(request: Request) -> frozenset[str] | None:
    """The actor names this principal may see.

    The audit trail is a deployment-level security record: an operator (admin)
    reads the whole trail; any other principal reads the entries naming
    themselves — their own logins, gate blocks, elevations. The scope is a
    *query* constraint (services.audit_query), evaluated before pagination, so
    another actor's entries are not merely off-page but out of the query.
    """
    user = _principal(request)
    if user.get("role") == "admin":
        return None
    names = {str(user.get(key)) for key in ("username", "id") if user.get(key)}
    return frozenset(names)


def _query_args(
    action: str | None, severity: str | None, actor: str | None
) -> dict[str, str | None]:
    return {
        "action": action or None,
        "severity": severity or None,
        "actor": actor or None,
    }


@router.get("")
def list_entries(
    request: Request,
    action: str | None = None,
    severity: str | None = None,
    actor: str | None = None,
    limit: int = DEFAULT_AUDIT_PAGE_SIZE,
    cursor: str | None = None,
) -> AuditPage:
    """One bounded, scope-filtered page of the audit trail, newest first.

    The envelope replaced a bare array: a page must be able to say there is
    more (`next_cursor`) without the client guessing. `limit` is clamped to
    [1, MAX_AUDIT_PAGE_SIZE]; a malformed cursor is a 400, not a silent page
    one — a client that echoes a cursor it did not get from this API is
    broken, and pretending otherwise would hide that.
    """
    try:
        return page_entries(
            stores.audit_log,
            **_query_args(action, severity, actor),
            limit=limit,
            cursor=cursor or None,
            actor_scope=_actor_scope(request),
            backend=stores.persistence_backend(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/export")
def export_entries(
    request: Request,
    action: str | None = None,
    severity: str | None = None,
    actor: str | None = None,
) -> StreamingResponse:
    """Stream the (scope- and cap-bounded) trail as NDJSON.

    Server-side this walks bounded pages through the same query seam as the
    list route — at most EXPORT_MAX_ENTRIES entries, a few hundred rows of
    memory at a time — so an export never materialises the corpus. Same scope
    contract as the list route: a non-admin exports their own entries only.
    """

    def generate():
        for entry in iter_export_entries(
            stores.audit_log,
            **_query_args(action, severity, actor),
            actor_scope=_actor_scope(request),
            backend=stores.persistence_backend(),
        ):
            yield json.dumps(entry, default=str) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="audit-log.ndjson"'},
    )


@router.get("/retention")
def retention_policy(request: Request) -> dict[str, Any]:
    """What this deployment's audit read surface keeps and bounds.

    Deployment-level constants, not corpus data — the same shape as
    /v1/dag-runs/retention (#697's rule: a bound nobody can see is a bound
    nobody can hold anyone to). The corpus itself is append-only today; the
    purge lane is #325. Declared before /{entry_id} so the parameterised
    route cannot swallow these paths.
    """
    _principal(request)
    return retention() | {
        "durable": stores.persistence_backend() is not None,
        "scope": "deployment" if _actor_scope(request) is None else "own",
    }


@router.get("/{entry_id}")
def get_entry(entry_id: str, request: Request) -> dict:
    """One entry, under the same scope contract as list and export.

    The detail route is a row-level read of the same corpus, so the same
    `_actor_scope` decision gates it: an operator reads any row, a non-admin
    only rows naming themselves. An out-of-scope row answers 404, not 403 —
    a 403 would confirm to the caller that another actor's entry exists,
    which is itself information the scope contract keeps from them.
    """

    scope = _actor_scope(request)
    entry = stores.audit_log.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="audit entry not found")
    if scope is not None and actor_of(entry) not in scope:
        raise HTTPException(status_code=404, detail="audit entry not found")
    return entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry


class CreateAuditBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str
    actor: str
    target: str | None = None
    detail: dict[str, Any] = {}
    severity: Literal["info", "warning", "critical"] = "info"


@router.post("", response_model=AuditEntry, status_code=201)
def create_entry(body: CreateAuditBody) -> AuditEntry:
    entry_id = str(uuid4())
    entry = AuditEntry(
        id=entry_id,
        action=body.action,
        actor=body.actor,
        target=body.target,
        detail=body.detail,
        severity=body.severity,
        created_at=_now(),
    )
    stores.audit_log[entry_id] = entry.model_dump(mode="json")
    return entry
