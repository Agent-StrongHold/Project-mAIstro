"""Master Orchestrator: dispatches work items across parallel agent groups.

Accepts a ConsolidationPlan (from Super Planner), breaks it into waves,
and dispatches each wave's work items to builder agents concurrently.
Tracks progress, handles failures, and gates stage transitions through
security scanning.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

logger = logging.getLogger("maistro.orchestrator")


class WorkItemStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass
class WorkItem:
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    group: str = ""
    task_id: str = ""
    description: str = ""
    agent_role: str = "mason"
    depends_on: list[str] = field(default_factory=list)
    status: WorkItemStatus = WorkItemStatus.PENDING
    result: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Wave:
    wave_number: int
    items: list[WorkItem] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class OrchestratorResult:
    plan_id: str
    total_items: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    waves_total: int = 0
    waves_completed: int = 0
    duration_seconds: float = 0.0


StageHandler = Callable[[WorkItem], Coroutine[Any, Any, WorkItem]]


class MasterOrchestrator:
    """Dispatches ConsolidationPlan waves to builder agents.

    Each wave runs its items concurrently. Waves execute sequentially
    (wave N+1 waits for wave N to complete). Failed items block
    dependent items in later waves.
    """

    def __init__(
        self,
        *,
        max_concurrent_per_wave: int = 5,
        max_retries: int = 2,
        security_gate: StageHandler | None = None,
    ) -> None:
        self._handlers: dict[str, StageHandler] = {}
        self._max_concurrent = max_concurrent_per_wave
        self._max_retries = max_retries
        self._security_gate = security_gate
        self._items: dict[str, WorkItem] = {}
        self._waves: list[Wave] = []
        self._xp_earned: dict[str, int] = {}

    def register_handler(self, agent_role: str, handler: StageHandler) -> None:
        self._handlers[agent_role] = handler

    def load_plan(self, waves: list[list[WorkItem]]) -> None:
        self._waves = [Wave(wave_number=i, items=items) for i, items in enumerate(waves)]
        self._items = {item.task_id: item for wave in self._waves for item in wave.items}

    def _check_dependencies(self, item: WorkItem) -> bool:
        for dep_id in item.depends_on:
            dep = self._items.get(dep_id)
            if dep is None or dep.status != WorkItemStatus.PASSED:
                return False
        return True

    async def _execute_item(self, item: WorkItem) -> WorkItem:
        if not self._check_dependencies(item):
            item.status = WorkItemStatus.BLOCKED
            item.result = f"Dependencies not met: {item.depends_on}"
            logger.warning("Blocked: %s (%s)", item.task_id, item.description)
            return item

        handler = self._handlers.get(item.agent_role)
        if handler is None:
            item.status = WorkItemStatus.FAILED
            item.result = f"No handler for agent role: {item.agent_role}"
            return item

        for attempt in range(self._max_retries + 1):
            try:
                item.status = WorkItemStatus.IN_PROGRESS
                item.started_at = datetime.now(UTC)
                result = await handler(item)
                item.status = result.status
                item.result = result.result
                item.metadata.update(result.metadata)
                item.completed_at = datetime.now(UTC)

                if self._security_gate and item.status == WorkItemStatus.PASSED:
                    sec_result = await self._security_gate(item)
                    if sec_result.status == WorkItemStatus.FAILED:
                        item.status = WorkItemStatus.FAILED
                        item.result = f"Security gate: {sec_result.result}"

                if item.status == WorkItemStatus.PASSED:
                    xp = item.metadata.get("xp_earned", 10)
                    self._xp_earned[item.agent_role] = self._xp_earned.get(item.agent_role, 0) + xp
                    return item

            except Exception as exc:
                logger.exception(
                    "Item %s failed (attempt %d/%d): %s",
                    item.task_id,
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                item.result = str(exc)

        item.status = WorkItemStatus.FAILED
        item.completed_at = datetime.now(UTC)
        return item

    async def _execute_wave(self, wave: Wave) -> None:
        wave.started_at = datetime.now(UTC)
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def _run(item: WorkItem) -> None:
            async with semaphore:
                await self._execute_item(item)

        await asyncio.gather(*[_run(item) for item in wave.items])
        wave.completed_at = datetime.now(UTC)

    async def execute(self) -> OrchestratorResult:
        started = datetime.now(UTC)
        plan_id = uuid4().hex[:12]

        for wave in self._waves:
            logger.info(
                "Wave %d: %d items",
                wave.wave_number,
                len(wave.items),
            )
            await self._execute_wave(wave)

        duration = (datetime.now(UTC) - started).total_seconds()
        total = len(self._items)
        completed = sum(1 for i in self._items.values() if i.status == WorkItemStatus.PASSED)
        failed = sum(1 for i in self._items.values() if i.status == WorkItemStatus.FAILED)

        return OrchestratorResult(
            plan_id=plan_id,
            total_items=total,
            completed=completed,
            failed=failed,
            skipped=total - completed - failed,
            waves_total=len(self._waves),
            waves_completed=sum(1 for w in self._waves if w.completed_at is not None),
            duration_seconds=duration,
        )

    def get_progress(self) -> dict[str, Any]:
        total = len(self._items)
        by_status: dict[str, int] = {}
        for item in self._items.values():
            by_status[item.status.value] = by_status.get(item.status.value, 0) + 1

        return {
            "total": total,
            "by_status": by_status,
            "xp_totals": dict(self._xp_earned),
            "waves_completed": sum(1 for w in self._waves if w.completed_at is not None),
            "waves_total": len(self._waves),
        }
