"""Persistence protocol for canonical durable graph checkpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from maistro.runs.model import RunStatus

from .hitl import HitlAuthorization
from .types import DurableRunRecord


@runtime_checkable
class DurableRunStore(Protocol):
    """Persist canonical Run + GraphExecutionState checkpoints."""

    async def create(self, record: DurableRunRecord) -> DurableRunRecord: ...

    async def get(self, run_id: str) -> DurableRunRecord | None: ...

    async def update(self, record: DurableRunRecord) -> DurableRunRecord:
        """Persist a strictly newer optimistic-concurrency version."""
        ...

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
        workspace_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[DurableRunRecord]:
        """Records in ``status``, oldest-created-first.

        ``after`` is a ``(created_at_iso, run_id)`` keyset cursor. Bounded
        fair scans (#1056, #1109) page through it instead of re-reading the
        same fixed prefix every tick.
        """
        ...

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
    ) -> list[DurableRunRecord]:
        """Return persisted graph continuations whose timed resume is due.

        ``after`` is a ``(resume_at_iso, run_id)`` keyset cursor over the same
        deadline-then-run_id order the due index uses (#1098).
        """
        ...

    async def list_hitl_due(
        self,
        *,
        authorization: HitlAuthorization,
        now: datetime,
        limit: int = 100,
    ) -> list[DurableRunRecord]:
        """Return due paused Runs visible to the effective principal."""
        ...

    async def list_hitl_paused(
        self,
        *,
        limit: int = 100,
        project_id: str | None = None,
        workspace_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[DurableRunRecord]:
        """Paused Runs whose durable frontier holds a human pause (#1109).

        Eligibility is queryable before ``limit``: the pause-kind projection
        answers "is any active node waiting on a person" from indexed state,
        so machine-only PAUSED Runs never occupy a page that human work behind
        them needs. It is a projection, not a second queue — each returned
        record is assembled from canonical state and revalidated against it;
        the pause entry, not the index, remains the source of truth.

        ``after`` is the same ``(created_at_iso, run_id)`` keyset cursor
        ``list_by_status`` uses. ``workspace_id`` is applied from the
        canonical Run; on stores whose index cannot carry Workspace scope it
        filters the assembled page, so callers paging across many Workspaces
        should pair it with a ``project_id`` (a Project belongs to exactly one
        Workspace) to keep the page's keyset over eligible rows only.
        """
        ...

    async def list_for_project(
        self, project_id: str, *, limit: int = 25
    ) -> list[DurableRunRecord]: ...

    async def submit_hitl_answer(
        self,
        run_id: str,
        node_id: str,
        answer: dict[str, Any],
        *,
        authorization: HitlAuthorization,
        at: datetime | None = None,
        workspace_id: str | None = None,
    ) -> DurableRunRecord:
        """Persist an answer and queue only a valid paused Run for resume."""
        ...

    async def timeout_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        authorization: HitlAuthorization,
        at: datetime | None = None,
        workspace_id: str | None = None,
    ) -> DurableRunRecord:
        """Terminalize a human pause whose persisted deadline elapsed."""
        ...

    async def cancel_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        authorization: HitlAuthorization,
        at: datetime | None = None,
        workspace_id: str | None = None,
    ) -> DurableRunRecord:
        """Terminalize a human pause by explicit cancellation."""
        ...


class RecoveryInfrastructureError(RuntimeError):
    """A persistence failure that makes continuing the recovery scan unsafe.

    Candidate-local resolver and execution failures are handled by the durable
    executor or by the recovery tick. Store adapters use this explicit type
    when a database/session failure invalidates every candidate in the tick.
    """


__all__ = ["DurableRunStore", "RecoveryInfrastructureError"]
