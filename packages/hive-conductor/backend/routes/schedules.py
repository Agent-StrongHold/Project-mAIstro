from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
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


def _canonical_context() -> tuple[Any, Any] | None:
    """Return the wired canonical schedule store and its Container."""
    try:
        from services.engine import get_engine

        container = getattr(getattr(get_engine(), "_agent_port", None), "container", None)
    except RuntimeError:
        return None
    store = getattr(container, "schedule_store", None)
    return (store, container) if store is not None else None


async def _canonical_projection(definition: Any) -> Schedule:
    from services.scheduler import _ScheduleRunner

    projected = _ScheduleRunner._surface_schedule(definition)
    stores.schedules[definition.schedule_id] = projected
    return cast(Schedule, projected)


@router.get("", response_model=list[Schedule])
async def list_schedules() -> list[Schedule]:
    context = _canonical_context()
    if context is None:
        return list(stores.schedules.values())
    store, _container = context
    return [await _canonical_projection(definition) for definition in await store.list_all()]


@router.get("/history")
def schedule_history() -> list:
    return []


@router.get("/{schedule_id}", response_model=Schedule)
async def get_schedule(schedule_id: str) -> Schedule:
    context = _canonical_context()
    if context is not None:
        definition = await context[0].get(schedule_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        return await _canonical_projection(definition)
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
async def create_schedule(body: CreateScheduleBody) -> Schedule:
    sid = str(uuid4())
    t = _now()
    context = _canonical_context()
    if context is not None:
        from services.scheduler import _ScheduleRunner

        from maistro.scheduling import Schedule as CanonicalSchedule

        store, container = context
        workspace_id, project_id = await _ScheduleRunner()._canonical_scope(body, container)
        definition = CanonicalSchedule(
            schedule_id=sid,
            workspace_id=workspace_id,
            project_id=project_id,
            name=body.name,
            description=body.description,
            cron=body.cron_expression,
            timezone=body.timezone,
            graph_template_id=body.mission_template_id,
            enabled=body.enabled,
            max_runs=body.max_runs,
            created_at=t,
            updated_at=t,
        )
        await store.put(definition)
        return await _canonical_projection(definition)

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
async def update_schedule(schedule_id: str, body: UpdateScheduleBody) -> Schedule:
    context = _canonical_context()
    if context is not None:
        from maistro.scheduling import Schedule as CanonicalSchedule

        store, _container = context
        definition = await store.get(schedule_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        values = body.model_dump(exclude_none=True)
        updates: dict[str, Any] = {"updated_at": _now()}
        field_map = {
            "name": "name",
            "description": "description",
            "cron_expression": "cron",
            "mission_template_id": "graph_template_id",
            "enabled": "enabled",
            "timezone": "timezone",
            "max_runs": "max_runs",
        }
        updates.update({field_map[key]: value for key, value in values.items()})
        if "cron_expression" in values or "timezone" in values:
            updates["next_due_at"] = None
        updated = CanonicalSchedule.model_validate(
            definition.model_copy(update=updates).model_dump()
        )
        await store.put(updated)
        return await _canonical_projection(updated)

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
async def delete_schedule(schedule_id: str) -> None:
    context = _canonical_context()
    if context is not None:
        if not await context[0].delete(schedule_id):
            raise HTTPException(status_code=404, detail="schedule not found")
        stores.schedules.pop(schedule_id, None)
        return
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
    context = _canonical_context()
    if context is None and schedule_id not in stores.schedules:
        raise HTTPException(status_code=404, detail="schedule not found")
    from services.scheduler import ScheduleNotFireable, fire_now

    try:
        await fire_now(schedule_id)
    except ScheduleNotFireable as exc:
        if "does not exist" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if context is not None:
        definition = await context[0].get(schedule_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        return await _canonical_projection(definition)
    return stores.schedules[schedule_id]
