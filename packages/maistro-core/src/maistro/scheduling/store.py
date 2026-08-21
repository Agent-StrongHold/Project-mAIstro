"""User-scheduled recurring tasks — store and data types.

Constraints:
- Max 10 tasks per user
- Minimum schedule interval: 15 minutes (validated via cron expression)
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

_CRON_FIELD_COUNT = 5

_FIELD_RANGES: list[tuple[int, int]] = [
    (0, 59),
    (0, 23),
    (1, 31),
    (1, 12),
    (0, 7),
]

_STEP_RE = re.compile(r"^\*/(\d+)$")
_RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
_LIST_RE = re.compile(r"^\d+(,\d+)*$")


def _validate_cron_field(value: str, field_min: int, field_max: int) -> bool:
    if value == "*":
        return True
    m = _STEP_RE.match(value)
    if m:
        step = int(m.group(1))
        return 1 <= step <= field_max
    m = _RANGE_RE.match(value)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return field_min <= lo <= field_max and field_min <= hi <= field_max and lo <= hi
    if _LIST_RE.match(value):
        return all(field_min <= int(v) <= field_max for v in value.split(","))
    if (
        value.isdigit()
    ):  # pragma: no cover — unreachable: _LIST_RE already matches any pure-digit string
        n = int(value)
        return field_min <= n <= field_max
    return False


_MIN_INTERVAL_MINUTES = 15


def _expand_field(value: str, field_min: int, field_max: int) -> list[int]:
    """Expand a (already validated) cron field into the sorted set of values it matches."""
    if value == "*":
        return list(range(field_min, field_max + 1))
    m = _STEP_RE.match(value)
    if m:
        step = int(m.group(1))
        return list(range(field_min, field_max + 1, step))
    m = _RANGE_RE.match(value)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return list(range(lo, hi + 1))
    if _LIST_RE.match(value):
        return sorted({int(v) for v in value.split(",")})
    return [int(value)]


def _min_gap_minutes(minute_field: str, hour_field: str) -> int:
    """Smallest gap (in minutes) between consecutive fire-times the schedule implies.

    Builds the full set of minute-of-day fire-times across a single representative
    day from the minute and hour fields, then returns the minimum gap between
    consecutive fires, wrapping across the midnight boundary.
    """
    minutes = _expand_field(minute_field, 0, 59)
    hours = _expand_field(hour_field, 0, 23)

    fires = sorted(h * 60 + mm for h in hours for mm in minutes)
    if len(fires) < 2:
        return 24 * 60  # at most once per day

    gaps = [b - a for a, b in pairwise(fires)]
    # Wrap-around: last fire of the day to the first fire of the next day.
    gaps.append((fires[0] + 24 * 60) - fires[-1])
    return min(gaps)


def validate_cron(expression: str) -> None:
    """Validate a cron expression (5-field format).

    Raises ValueError for invalid expressions or intervals shorter than 15 minutes.
    """
    parts = expression.strip().split()
    if len(parts) != _CRON_FIELD_COUNT:
        msg = f"Invalid cron expression: expected {_CRON_FIELD_COUNT} fields, got {len(parts)}"
        raise ValueError(msg)

    for i, (part, (fmin, fmax)) in enumerate(zip(parts, _FIELD_RANGES, strict=True)):
        if not _validate_cron_field(part, fmin, fmax):
            field_names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
            msg = f"Invalid cron expression: bad {field_names[i]} field '{part}'"
            raise ValueError(msg)

    minute_field = parts[0]
    hour_field = parts[1]

    if _min_gap_minutes(minute_field, hour_field) < _MIN_INTERVAL_MINUTES:
        msg = "Schedule too frequent: minimum interval is 15 min"
        raise ValueError(msg)


@dataclass
class ScheduledTask:
    """A user-created recurring task."""

    id: str = ""
    user_id: str = ""
    name: str = ""
    schedule: str = ""
    prompt: str = ""
    agent: str = ""
    delivery: str = ""
    enabled: bool = True
    created_at: float = 0.0
    last_run_at: float = 0.0
    run_count: int = 0


@dataclass
class TaskExecution:
    """Record of a single task execution."""

    id: str = ""
    task_id: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    status: str = ""
    result_preview: str = ""


MAX_TASKS_PER_USER = 10


@dataclass
class InMemoryScheduleStore:
    """In-memory store for scheduled tasks. PostgreSQL version for production."""

    _tasks: dict[str, ScheduledTask] = field(default_factory=dict)
    _executions: dict[str, list[TaskExecution]] = field(default_factory=dict)

    async def create(self, task: ScheduledTask) -> ScheduledTask:
        validate_cron(task.schedule)

        user_count = sum(1 for t in self._tasks.values() if t.user_id == task.user_id)
        if user_count >= MAX_TASKS_PER_USER:
            msg = f"User has reached the maximum of {MAX_TASKS_PER_USER} scheduled tasks"
            raise ValueError(msg)

        task.id = str(uuid.uuid4())[:8]
        task.created_at = time.time()
        self._tasks[task.id] = task
        return task

    async def get(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    async def list_for_user(self, *, user_id: str) -> list[ScheduledTask]:
        return [t for t in self._tasks.values() if t.user_id == user_id]

    async def update(self, task_id: str, **fields: Any) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None

        if "schedule" in fields:
            validate_cron(fields["schedule"])

        for key, value in fields.items():
            if hasattr(task, key) and key not in ("id", "user_id", "created_at"):
                setattr(task, key, value)
        return task

    async def delete(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        del self._tasks[task_id]
        self._executions.pop(task_id, None)
        return True

    async def record_execution(self, task_id: str, execution: TaskExecution) -> None:
        if task_id not in self._executions:
            self._executions[task_id] = []
        self._executions[task_id].append(execution)

    async def get_history(self, task_id: str, limit: int = 10) -> list[TaskExecution]:
        if task_id not in self._tasks:
            return []
        executions = self._executions.get(task_id, [])
        return list(reversed(executions))[:limit]

    async def list_enabled(self) -> list[ScheduledTask]:
        return [t for t in self._tasks.values() if t.enabled]
