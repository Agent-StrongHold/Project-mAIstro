from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

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


@router.get("")
def list_entries(
    action: str | None = None, severity: str | None = None, actor: str | None = None
) -> list[dict]:
    entries = list(stores.audit_log.values())

    def _field(e: object, name: str) -> str:
        if isinstance(e, dict):
            return e.get(name, "")
        return getattr(e, name, "")

    if action is not None:
        entries = [e for e in entries if _field(e, "action") == action]
    if severity is not None:
        entries = [e for e in entries if _field(e, "severity") == severity]
    if actor is not None:
        entries = [e for e in entries if _field(e, "actor") == actor]
    return [e.model_dump(mode="json") if hasattr(e, "model_dump") else e for e in entries]


@router.get("/{entry_id}")
def get_entry(entry_id: str) -> dict:
    if entry_id not in stores.audit_log:
        raise HTTPException(status_code=404, detail="audit entry not found")
    entry = stores.audit_log[entry_id]
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
