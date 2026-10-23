from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from services.audit_bridge import hive_entry_to_core, list_core_audit_entries, write_core_audit_sync

router = APIRouter(tags=["audit"])

logger = logging.getLogger(__name__)


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


@router.get("")
async def list_entries(
    action: str | None = None, severity: str | None = None, actor: str | None = None
) -> list[dict]:
    return await audit_entries_view(action=action, severity=severity, actor=actor)


async def audit_entries_view(
    action: str | None = None, severity: str | None = None, actor: str | None = None
) -> list[dict]:
    """The one audit-log read every surface shares (#389).

    `GET /v1/audit`, the settings-change trail and the schedule fire history
    all serve the same durable log, so they share this read: the core
    Sentinel store when a Container exposes one, otherwise the same rows from
    the hive dict `log_audit` wrote (unit tests, boot ordering). Both legs
    return the Hive HTTP shape, so callers filter and sort identically.
    """
    core_entries = await list_core_audit_entries(action=action, severity=severity, actor=actor)
    if core_entries is not None:
        return core_entries

    entries = list(stores.audit_log.values())

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


async def audit_entries_view(request: Request, *, action: str) -> AsyncIterator[dict[str, Any]]:
    """Stream a projection's action from the same authority, one bounded page at a time.

    Settings and schedule-history callers enforce their existing settings/workspace
    permissions on legacy records. These are not personal actor-scoped views:
    scheduler receipts name the system actor. A bound Sentinel authority still
    requires admin (ADR-073), before any query, even on these secondary surfaces.
    Callers cap their output and never accumulate the whole stream.
    """
    audit_log = _authorized_core_audit(_actor_scope(request))
    backend = stores.persistence_backend()
    cursor = None
    while True:
        if audit_log is not None:
            page = await page_core_audit_entries(
                audit_log, action=action, limit=DEFAULT_AUDIT_PAGE_SIZE, cursor=cursor
            )
        else:
            page = page_entries(
                stores.audit_log,
                action=action,
                limit=DEFAULT_AUDIT_PAGE_SIZE,
                cursor=cursor,
                backend=backend,
            )
        for entry in page.entries:
            yield entry
        if not page.entries or page.next_cursor is None:
            return
        cursor = page.next_cursor


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


@router.get("/retention", response_model=AuditRetention)
def retention_policy(request: Request) -> AuditRetention:
    """What this deployment's audit read surface keeps and bounds.

    Deployment-level constants, not corpus data — the same shape as
    /v1/dag-runs/retention (#697's rule: a bound nobody can see is a bound
    nobody can hold anyone to). The corpus itself is append-only today; the
    purge lane is #325. Declared before /{entry_id} so the parameterised
    route cannot swallow these paths.
    """
    require_principal(request)
    return AuditRetention(
        **retention(),
        durable=stores.persistence_backend() is not None,
        scope="deployment" if _actor_scope(request) is None else "own",
    )


@router.get("/{entry_id}")
def get_entry(entry_id: str, request: Request) -> dict:
    """One entry, under the same scope contract as list and export.

    When a canonical authority is bound, ADR-073's admin gate also protects
    mirrored legacy detail IDs, before any lookup. Without that binding an
    operator reads any legacy row, a non-admin only rows naming themselves.
    An out-of-scope legacy row answers 404 to avoid confirming its existence.
    """

    scope = _actor_scope(request)
    _authorized_core_audit(scope)
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
