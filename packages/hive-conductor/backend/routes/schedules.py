from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import stores
from fastapi import APIRouter, HTTPException
from models.schemas import Schedule
from pydantic import BaseModel, ConfigDict, field_validator

router = APIRouter(tags=["schedules"])


def _now() -> datetime:
    return datetime.now(UTC)


def _check_timezone(value: str | None) -> str | None:
    """Reject a zone the recurrence engine cannot read, at the boundary.

    The canonical `maistro.scheduling.Schedule` resolves the zone in its own
    validator, but the `/v1/schedules` row is a separate model that stores
    whatever it is given. An unreadable zone would therefore be accepted here
    and then raise inside `_as_definition` on every tick, where
    `_evaluate_schedule`'s caller catches it and logs a warning — a schedule
    that silently never fires and reports `enabled: true` forever. 422 now is
    the only place this is visible to whoever made the mistake.
    """
    if value is None:
        # The update body's "leave alone". Validating it as a zone would make
        # every partial update that omits the field a 422.
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {value!r}") from exc
    return value


def _check_max_runs(value: int | None) -> int | None:
    """A bound below 1 is a schedule that may never fire; say so as a 422.

    `maistro.scheduling.Schedule` raises `ValueError` for it, which reaches the
    tick rather than the caller for the same reason as the zone above.
    """
    if value is not None and value < 1:
        raise ValueError("max_runs must be at least 1 when set")
    return value


@router.get("", response_model=list[Schedule])
def list_schedules() -> list[Schedule]:
    return list(stores.schedules.values())


@router.get("/history")
def schedule_history() -> list:
    return []


@router.get("/{schedule_id}", response_model=Schedule)
def get_schedule(schedule_id: str) -> Schedule:
    if schedule_id not in stores.schedules:
        raise HTTPException(status_code=404, detail="schedule not found")
    return stores.schedules[schedule_id]


class CreateScheduleBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    cron_expression: str
    mission_template_id: str
    enabled: bool = True
    timezone: str = "UTC"
    max_runs: int | None = None

    _tz = field_validator("timezone")(_check_timezone)
    _bound = field_validator("max_runs")(_check_max_runs)


@router.post("", response_model=Schedule, status_code=201)
def create_schedule(body: CreateScheduleBody) -> Schedule:
    sid = str(uuid4())
    t = _now()
    schedule = Schedule(
        id=sid,
        name=body.name,
        description=body.description,
        cron_expression=body.cron_expression,
        mission_template_id=body.mission_template_id,
        enabled=body.enabled,
        timezone=body.timezone,
        max_runs=body.max_runs,
        last_run=None,
        last_run_id=None,
        next_run=None,
        created_at=t,
        updated_at=t,
    )
    stores.schedules[sid] = schedule
    return schedule


class UpdateScheduleBody(BaseModel):
    """A partial update. `None` means "leave alone", not "clear".

    That is this endpoint's existing contract — `exclude_none=True` below —
    and `max_runs` inherits it, so a bound cannot be *removed* through this
    body once set. Recreating the schedule is the way to unbound it. Stated
    here because for `max_runs` the omission is easy to read as a clear.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    mission_template_id: str | None = None
    enabled: bool | None = None
    timezone: str | None = None
    max_runs: int | None = None

    _tz = field_validator("timezone")(_check_timezone)
    _bound = field_validator("max_runs")(_check_max_runs)


@router.put("/{schedule_id}", response_model=Schedule)
def update_schedule(schedule_id: str, body: UpdateScheduleBody) -> Schedule:
    if schedule_id not in stores.schedules:
        raise HTTPException(status_code=404, detail="schedule not found")
    schedule = stores.schedules[schedule_id]
    updates = body.model_dump(exclude_none=True)
    t = _now()
    updates["updated_at"] = t
    schedule = schedule.model_copy(update=updates)
    stores.schedules[schedule_id] = schedule
    return schedule


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str) -> None:
    if schedule_id not in stores.schedules:
        raise HTTPException(status_code=404, detail="schedule not found")
    stores.schedules.pop(schedule_id)


@router.post("/{schedule_id}/run", response_model=Schedule)
async def run_schedule(schedule_id: str) -> Schedule:
    """Fire the schedule now, for real.

    This used to stamp `last_run` and return — no Run created, no cursor
    advanced, nothing counted against `max_runs`. The schedule then reported a
    fire that no `run_id` anywhere corresponded to, which is the defect #231
    removed from the tick path and missed here.

    A fire that cannot happen is a 409 rather than a silent stamp: the caller
    asked for work to start, and it did not.
    """
    if schedule_id not in stores.schedules:
        raise HTTPException(status_code=404, detail="schedule not found")
    from services.scheduler import ScheduleNotFireable, fire_now

    try:
        await fire_now(schedule_id)
    except ScheduleNotFireable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return stores.schedules[schedule_id]
