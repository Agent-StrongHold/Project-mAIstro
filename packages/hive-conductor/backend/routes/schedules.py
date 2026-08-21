from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException
from models.schemas import Schedule
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["schedules"])


def _now() -> datetime:
    return datetime.now(UTC)


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
        last_run=None,
        next_run=None,
        created_at=t,
        updated_at=t,
    )
    stores.schedules[sid] = schedule
    return schedule


class UpdateScheduleBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    mission_template_id: str | None = None
    enabled: bool | None = None


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
def run_schedule(schedule_id: str) -> Schedule:
    if schedule_id not in stores.schedules:
        raise HTTPException(status_code=404, detail="schedule not found")
    t = _now()
    schedule = stores.schedules[schedule_id]
    schedule = schedule.model_copy(update={"last_run": t, "updated_at": t})
    stores.schedules[schedule_id] = schedule
    return schedule
