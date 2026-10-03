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
from services.audit_bridge import (
    core_audit_log,
    hive_entry_to_core,
    page_core_audit_entries,
    write_core_audit_sync,
)
from services.audit_query import (
    DEFAULT_AUDIT_PAGE_SIZE,
    EXPORT_MAX_ENTRIES,
    AuditPage,
    actor_of,
    iter_export_entries,
    page_entries,
    retention,
)
from services.request_principal import require_principal

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
    created_at = _now()
    entry = AuditEntry(
        id=entry_id,
        action=action,
        actor=actor,
        target=target,
        detail=detail or {},
        severity=severity,
        created_at=created_at,
    )
    stores.audit_log[entry_id] = entry.model_dump(mode="json")
    write_core_audit_sync(
        hive_entry_to_core(
            entry_id=entry_id,
            action=action,
            actor=actor,
            target=target,
            detail=detail,
            severity=severity,
            created_at=created_at,
        )
    )


def _actor_scope(request: Request) -> frozenset[str] | None:
    """The actor names this principal may see.

    The audit trail is a deployment-level security record: an operator (admin)
    reads the whole trail; any other principal reads the entries naming
    themselves — their own logins, gate blocks, elevations. The scope is a
    *query* constraint (services.audit_query), evaluated before pagination, so
    another actor's entries are not merely off-page but out of the query.
    """
    principal = require_principal(request)
    if principal.is_admin:
        return None
    return frozenset(name for name in (principal.username, principal.user_id) if name)


def _query_args(
    action: str | None, severity: str | None, actor: str | None
) -> dict[str, str | None]:
    return {
        "action": action or None,
        "severity": severity or None,
        "actor": actor or None,
    }


@router.get("")
async def list_entries(
    request: Request,
    action: str | None = None,
    severity: str | None = None,
    actor: str | None = None,
    limit: int = DEFAULT_AUDIT_PAGE_SIZE,
    cursor: str | None = None,
) -> AuditPage:
    """Bounded pages from the bound authority, with authorization before I/O.

    Core decision audit is admin-only (ADR-073). Only deployments without a
    core binding use the scoped legacy store; never switch corpora mid-query.
    """
    scope = _actor_scope(request)
    audit_log = _authorized_core_audit(scope)
    try:
        if audit_log is not None:
            return await page_core_audit_entries(
                audit_log,
                **_query_args(action, severity, actor),
                limit=limit,
                cursor=cursor or None,
            )
        return page_entries(
            stores.audit_log,
            **_query_args(action, severity, actor),
            limit=limit,
            cursor=cursor or None,
            actor_scope=scope,
            backend=stores.persistence_backend(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _authorized_core_audit(scope: frozenset[str] | None) -> Any | None:
    audit_log = core_audit_log()
    if audit_log is not None and scope is not None:
        raise HTTPException(status_code=403, detail="Audit administrator required")
    return audit_log


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
    contract as the list route: canonical decisions require admin; only the
    unbound legacy fallback permits a non-admin's own entries.
    """

    scope = _actor_scope(request)
    audit_log = _authorized_core_audit(scope)

    async def generate_core():
        cursor = None
        emitted = 0
        while emitted < EXPORT_MAX_ENTRIES:
            page = await page_core_audit_entries(
                audit_log,
                **_query_args(action, severity, actor),
                limit=min(DEFAULT_AUDIT_PAGE_SIZE, EXPORT_MAX_ENTRIES - emitted),
                cursor=cursor,
            )
            for entry in page.entries:
                yield json.dumps(entry, default=str) + "\n"
            emitted += len(page.entries)
            if not page.entries or page.next_cursor is None:
                return
            cursor = page.next_cursor

    def generate():
        for entry in iter_export_entries(
            stores.audit_log,
            **_query_args(action, severity, actor),
            actor_scope=scope,
            backend=stores.persistence_backend(),
        ):
            yield json.dumps(entry, default=str) + "\n"

    return StreamingResponse(
        generate_core() if audit_log is not None else generate(),
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
    require_principal(request)
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
