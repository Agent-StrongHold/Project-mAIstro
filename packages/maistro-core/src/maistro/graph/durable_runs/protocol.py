"""Persistence protocol for canonical durable graph checkpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from maistro.runs.model import RunStatus

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
    ) -> list[DurableRunRecord]: ...

    async def list_due(self, *, now: datetime, limit: int = 100) -> list[DurableRunRecord]:
        """Return persisted graph continuations whose timed resume is due."""
        ...

    async def list_for_project(
        self, project_id: str, *, limit: int = 25
    ) -> list[DurableRunRecord]: ...

    async def submit_hitl_answer(
        self,
        run_id: str,
        node_id: str,
        answer: dict[str, Any],
    ) -> DurableRunRecord:
        """Attach an answer and queue the paused canonical Run for resume."""
        ...


__all__ = ["DurableRunStore"]
