"""Durable approval request persistence for resumable human-in-the-loop execution.

The existing Approval provider protocol may still offer a synchronous-awaiting
experience to callers. Canonical Run execution needs a lower-level primitive:
issue a request, persist it, release the worker, and resolve it later from a
UI/CLI/API before a new Attempt resumes the logical NodeRun.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro.capabilities.slots.approval import ApprovalRequest

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
)
_REDACTED = "[REDACTED]"


def approval_request_digest(request: Any) -> str:
    """Return a stable digest that binds approval to the exact requested effect payload."""

    payload = json.dumps(
        request,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def redact_approval_value(value: Any) -> Any:
    """Recursively redact likely credentials before approval context is persisted."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if lowered == "pat" or any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                redacted[key] = _REDACTED
            else:
                redacted[key] = redact_approval_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_approval_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_approval_value(item) for item in value]
    return value


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class DurableApproval(BaseModel):
    """Persisted human decision request correlated to canonical execution IDs."""

    model_config = ConfigDict(extra="forbid")

    request: ApprovalRequest
    workspace_id: str
    project_id: str
    run_id: str
    node_run_id: str
    attempt_id: str
    binding_id: str
    effect_key: str
    request_digest: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    actor: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_state(self) -> DurableApproval:
        required = {
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "node_run_id": self.node_run_id,
            "attempt_id": self.attempt_id,
            "binding_id": self.binding_id,
            "effect_key": self.effect_key,
        }
        for field, value in required.items():
            if not value.strip():
                raise ValueError(f"{field} must be a non-empty string")
        if not self.request_digest:
            self.request_digest = str(self.request.params.get("request_digest") or "")
        if not self.request_digest:
            legacy_payload = self.request.params.get("request", self.request.params)
            self.request_digest = approval_request_digest(legacy_payload)
        terminal = self.status in {ApprovalStatus.APPROVED, ApprovalStatus.DENIED}
        if terminal and self.resolved_at is None:
            raise ValueError("resolved approval requires resolved_at")
        if not terminal and self.resolved_at is not None:
            raise ValueError("pending approval cannot have resolved_at")
        return self

    @property
    def effect_identity(self) -> tuple[str, str, str, str]:
        return (self.run_id, self.node_run_id, self.binding_id, self.effect_key)


@runtime_checkable
class ApprovalStore(Protocol):
    async def create(self, approval: DurableApproval) -> DurableApproval: ...

    async def get(self, request_id: str) -> DurableApproval | None: ...

    async def find_effect(
        self,
        *,
        run_id: str,
        node_run_id: str,
        binding_id: str,
        effect_key: str,
    ) -> DurableApproval | None: ...

    async def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        actor: str = "",
    ) -> DurableApproval: ...


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, DurableApproval] = {}
        self._lock = asyncio.Lock()

    async def create(self, approval: DurableApproval) -> DurableApproval:
        async with self._lock:
            request_id = approval.request.request_id
            if request_id in self._items:
                raise ValueError(f"approval request {request_id!r} already exists")
            for existing in self._items.values():
                if existing.effect_identity == approval.effect_identity:
                    return existing.model_copy(deep=True)
            persisted = approval.model_copy(deep=True)
            self._items[request_id] = persisted
            return persisted.model_copy(deep=True)

    async def get(self, request_id: str) -> DurableApproval | None:
        approval = self._items.get(request_id)
        return approval.model_copy(deep=True) if approval is not None else None

    async def find_effect(
        self,
        *,
        run_id: str,
        node_run_id: str,
        binding_id: str,
        effect_key: str,
    ) -> DurableApproval | None:
        identity = (run_id, node_run_id, binding_id, effect_key)
        for approval in self._items.values():
            if approval.effect_identity == identity:
                return approval.model_copy(deep=True)
        return None

    async def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        actor: str = "",
    ) -> DurableApproval:
        async with self._lock:
            existing = self._items.get(request_id)
            if existing is None:
                raise KeyError(f"approval request {request_id!r} does not exist")
            if existing.status is not ApprovalStatus.PENDING:
                return existing.model_copy(deep=True)
            resolved = existing.model_copy(
                update={
                    "status": ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED,
                    "actor": actor,
                    "resolved_at": datetime.now(UTC),
                }
            )
            self._items[request_id] = resolved
            return resolved.model_copy(deep=True)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_approvals (
    request_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_run_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    effect_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(run_id, node_run_id, binding_id, effect_key)
)
"""


class SqliteApprovalStore:
    """SQLite persistence for approval requests that survive process restart."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()

    async def create(self, approval: DurableApproval) -> DurableApproval:
        existing = await self.find_effect(
            run_id=approval.run_id,
            node_run_id=approval.node_run_id,
            binding_id=approval.binding_id,
            effect_key=approval.effect_key,
        )
        if existing is not None:
            return existing
        async with self._lock:
            try:
                await self._conn.execute(
                    """INSERT INTO capability_approvals
                       (request_id, run_id, node_run_id, binding_id, effect_key, payload)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        approval.request.request_id,
                        approval.run_id,
                        approval.node_run_id,
                        approval.binding_id,
                        approval.effect_key,
                        approval.model_dump_json(),
                    ),
                )
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raced = await self.find_effect(
                    run_id=approval.run_id,
                    node_run_id=approval.node_run_id,
                    binding_id=approval.binding_id,
                    effect_key=approval.effect_key,
                )
                if raced is not None:
                    return raced
                raise
        return approval.model_copy(deep=True)

    async def get(self, request_id: str) -> DurableApproval | None:
        cursor = await self._conn.execute(
            "SELECT payload FROM capability_approvals WHERE request_id = ?",
            (request_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return DurableApproval.model_validate_json(str(row[0]))

    async def find_effect(
        self,
        *,
        run_id: str,
        node_run_id: str,
        binding_id: str,
        effect_key: str,
    ) -> DurableApproval | None:
        cursor = await self._conn.execute(
            """SELECT payload FROM capability_approvals
               WHERE run_id = ? AND node_run_id = ? AND binding_id = ? AND effect_key = ?""",
            (run_id, node_run_id, binding_id, effect_key),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return DurableApproval.model_validate_json(str(row[0]))

    async def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        actor: str = "",
    ) -> DurableApproval:
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self._conn.execute(
                    "SELECT payload FROM capability_approvals WHERE request_id = ?",
                    (request_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise KeyError(f"approval request {request_id!r} does not exist")
                existing = DurableApproval.model_validate_json(str(row[0]))
                if existing.status is not ApprovalStatus.PENDING:
                    await self._conn.commit()
                    return existing
                resolved = existing.model_copy(
                    update={
                        "status": ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED,
                        "actor": actor,
                        "resolved_at": datetime.now(UTC),
                    }
                )
                await self._conn.execute(
                    "UPDATE capability_approvals SET payload = ? WHERE request_id = ?",
                    (resolved.model_dump_json(), request_id),
                )
                await self._conn.commit()
                return resolved
            except BaseException:
                await self._conn.rollback()
                raise


__all__ = [
    "ApprovalStatus",
    "ApprovalStore",
    "DurableApproval",
    "InMemoryApprovalStore",
    "SqliteApprovalStore",
    "approval_request_digest",
    "redact_approval_value",
]
