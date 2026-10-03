from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import stores
from config import get_settings
from fastapi import APIRouter, Header, HTTPException, Request
from models.schemas import Schedule
from pydantic import BaseModel, ConfigDict, field_validator
from services import dag_run_inspection, workspace_authority
from services.dag_execution_scope import (
    DagWorkspaceSelectionError,
    authorize_hive_dag_scope,
    authorize_hive_dag_workspace,
)

from maistro.scheduling.cron import CronParseError, minimum_gap
from maistro.scheduling.model import DEFAULT_CATCHUP_WINDOW_SECONDS, MAX_CATCHUP_WINDOW_SECONDS

logger = logging.getLogger(__name__)

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


def _check_catchup_window(value: float | None) -> float | None:
    """Bound the catch-up window a client may request (#1200), as a 422.

    After downtime the window decides how much missed work one evaluation will
    consider, so an unbounded window is an unbounded backlog: the product cap
    (`schedule_max_catchup_window_s`, itself bounded at startup) is what keeps
    a client from asking for one. Zero stays legal — it means "never backfill"
    — and `None` is the update body's "leave alone". The substrate's own
    ceiling (`MAX_CATCHUP_WINDOW_SECONDS`) is never the binding constraint
    here because the operator cap cannot be configured above it, but the
    canonical model would reject it at the write below anyway; naming this
    layer's own bound keeps the 422 about the product's rule.
    """
    if value is None:
        return None
    if value < 0:
        raise ValueError("catchup_window_seconds cannot be negative")
    if value > MAX_CATCHUP_WINDOW_SECONDS:
        raise ValueError(
            f"catchup_window_seconds must be at most {MAX_CATCHUP_WINDOW_SECONDS:g} (seven days)"
        )
    if value > get_settings().schedule_max_catchup_window_s:
        raise ValueError(
            "catchup_window_seconds must be at most "
            f"{get_settings().schedule_max_catchup_window_s} "
            "(schedule_max_catchup_window_s)"
        )
    return value


def _frequency_gap(cron_expression: str, timezone: str) -> timedelta:
    """The recurrence's shortest real gap, or a 422 for an unreadable cron.

    `minimum_gap` measures consecutive fire times, so list/step/range forms
    are all honored — `0,5,10 * * * *` is a five-minute schedule, not an
    hourly one (ADR-082126-f69c §7).
    """
    try:
        return minimum_gap(cron_expression, timezone=timezone)
    except CronParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_supported_frequency(cron_expression: str, timezone: str) -> timedelta:
    """The product frequency floor (#1200), enforced as a 422.

    The substrate measures and does not decide (ADR-082126-f69c §7: rate
    floors are product policy); this route is where the product decides. The
    floor is the operator's `schedule_min_frequency_gap_s`, so what "too
    often" means is deployment configuration — but the setting itself is
    bounded at startup, which is what keeps a misconfiguration from quietly
    accepting a busy-loop schedule.
    """
    gap = _frequency_gap(cron_expression, timezone)
    floor = get_settings().schedule_min_frequency_gap_s
    if gap < timedelta(seconds=floor):
        raise HTTPException(
            status_code=422,
            detail=(
                f"cron_expression {cron_expression!r} can fire every "
                f"{gap.total_seconds():g}s; the minimum supported frequency is one "
                f"fire per {floor}s (schedule_min_frequency_gap_s)"
            ),
        )
    return gap


def _check_fire_id(value: str | None) -> str | None:
    """A manual fire's identity is an opaque token, bounded, and non-empty.

    An empty or whitespace token would mint `"manual:" + ""` as an occurrence
    identity shared by every such request — the opposite of the stable
    per-logical-request identity it exists to be.  The length bound keeps a
    stray paste from smuggling unbounded data into durable Run provenance.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("fire_id must be a non-empty token when set")
    if len(stripped) > 200:
        raise ValueError("fire_id must be at most 200 characters")
    return stripped


def _actor(request: Request) -> str:
    """The authenticated principal; a schedule is never owned by "system"."""
    user = getattr(request.state, "user", None) or {}
    actor = str(user.get("id") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="authentication required")
    return actor


async def _visible_schedule(request: Request, schedule_id: str) -> Schedule:
    """The row, if the caller is a member of its Workspace; else one 404.

    Missing, ownerless and foreign rows share the refusal so this route is
    not an existence oracle for other Workspaces' schedules.
    """
    actor = _actor(request)
    schedule = stores.schedules.get(schedule_id)
    if schedule is None or not await workspace_authority.is_member(actor, schedule.workspace_id):
        raise HTTPException(status_code=404, detail="schedule not found")
    # Re-read after the await: a concurrent delete or fire may have landed,
    # and acting on the pre-await copy would resurrect or rewind the row.
    current = stores.schedules.get(schedule_id)
    if current is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return current


_WRITER_ROLES = frozenset({"owner", "editor"})
_SCOPE_REFUSED = "Schedule Workspace scope is not authorized"


async def _require_writer(actor: str, workspace_id: str) -> None:
    """A viewer may read a Workspace's schedules, not arm or retarget them."""
    if await workspace_authority.member_role(actor, workspace_id) not in _WRITER_ROLES:
        raise HTTPException(status_code=403, detail=_SCOPE_REFUSED)


async def _writable_schedule(
    request: Request, schedule_id: str, *, require_active: bool = True
) -> Schedule:
    """A visible row the caller may change; an archived Workspace admits no
    edit or Run, the same admission `POST /v1/dags/{id}/run` applies."""
    schedule = await _visible_schedule(request, schedule_id)
    actor = _actor(request)
    await _require_writer(actor, schedule.workspace_id)
    if require_active:
        try:
            await authorize_hive_dag_workspace(workspace_id=schedule.workspace_id, user_id=actor)
        except DagWorkspaceSelectionError as exc:
            raise HTTPException(status_code=403, detail=_SCOPE_REFUSED) from exc
    current = stores.schedules.get(schedule_id)
    if current is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return current


async def _write_canonical(schedule: Schedule) -> None:
    """Write the canonical definition before its Hive projection (#1199)."""
    from services.scheduler import ScheduleAdmissionUnavailable, put_canonical_definition

    try:
        await put_canonical_definition(schedule.id, schedule)
    except ScheduleAdmissionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[Schedule])
async def list_schedules(request: Request) -> list[Schedule]:
    allowed = await dag_run_inspection.authorized_workspace_ids(_actor(request))
    return [
        row for row in stores.schedules.values() if row.workspace_id and row.workspace_id in allowed
    ]


@router.get("/history")
def schedule_history() -> list:
    return []


@router.get("/{schedule_id}", response_model=Schedule)
async def get_schedule(schedule_id: str, request: Request) -> Schedule:
    return await _visible_schedule(request, schedule_id)


class CreateScheduleBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    cron_expression: str
    mission_template_id: str
    enabled: bool = True
    timezone: str = "UTC"
    max_runs: int | None = None
    catchup_window_seconds: float = DEFAULT_CATCHUP_WINDOW_SECONDS
    # Selections, not authority: the create route admits them through the
    # canonical Workspace/Project service before anything is stored.
    workspace_id: str = ""
    project_id: str = ""

    _tz = field_validator("timezone")(_check_timezone)
    _bound = field_validator("max_runs")(_check_max_runs)
    _window = field_validator("catchup_window_seconds")(_check_catchup_window)


@router.post("", response_model=Schedule, status_code=201)
async def create_schedule(body: CreateScheduleBody, request: Request) -> Schedule:
    actor = _actor(request)
    try:
        scope = await authorize_hive_dag_scope(
            workspace_id=body.workspace_id, user_id=actor, project_id=body.project_id
        )
    except DagWorkspaceSelectionError as exc:
        raise HTTPException(status_code=403, detail=_SCOPE_REFUSED) from exc
    await _require_writer(actor, scope.workspace_id)
    # The floor is a create-time rule too (#1200): a busy-loop recurrence is
    # refused before any row exists, exactly like an unreadable cron.
    _require_supported_frequency(body.cron_expression, body.timezone)
    sid = str(uuid4())
    t = _now()
    schedule = Schedule(
        id=sid,
        user_id=scope.user_id,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
        name=body.name,
        description=body.description,
        cron_expression=body.cron_expression,
        mission_template_id=body.mission_template_id,
        enabled=body.enabled,
        timezone=body.timezone,
        max_runs=body.max_runs,
        catchup_window_seconds=body.catchup_window_seconds,
        last_run=None,
        last_run_id=None,
        next_run=None,
        created_at=t,
        updated_at=t,
    )
    await _write_canonical(schedule)
    try:
        stores.schedules[sid] = schedule
    except Exception:
        # The canonical write above already committed (Codex, #1199): a
        # failed second write must not leave an enabled canonical row behind
        # that no Hive-keyed route can reach -- creation failed, so there is
        # no Hive row for GET/PUT/DELETE to find it by, and startup backfill
        # only ever adds rows, never removes one. Best-effort compensation;
        # its own failure is logged and swallowed so the caller sees the real
        # failure below, not this cleanup's.
        from services.scheduler import delete_canonical_definition

        try:
            await delete_canonical_definition(sid)
        except Exception:
            logger.warning(
                "Failed to compensate canonical schedule %s after a failed Hive write", sid
            )
        raise
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
    catchup_window_seconds: float | None = None

    _tz = field_validator("timezone")(_check_timezone)
    _bound = field_validator("max_runs")(_check_max_runs)
    _window = field_validator("catchup_window_seconds")(_check_catchup_window)


@router.put("/{schedule_id}", response_model=Schedule)
async def update_schedule(schedule_id: str, body: UpdateScheduleBody, request: Request) -> Schedule:
    await _writable_schedule(request, schedule_id)
    from services.scheduler import definition_lock

    updates = body.model_dump(exclude_none=True)
    async with definition_lock(schedule_id):
        current = stores.schedules.get(schedule_id)
        if current is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        # The floor applies to the *effective* recurrence (#1200): a request
        # that touches the recurrence — cron or zone, either of which can
        # change when fires land — must bring it up to the floor, while one
        # that edits only a name (or any other field) leaves a schedule filed
        # before the floor existed exactly as it is. Refusing the unrelated
        # edit would strand the row: its owner could not rename it without
        # first recreating it, which is enforcement turning into bricking.
        if "cron_expression" in updates or "timezone" in updates:
            _require_supported_frequency(
                str(updates.get("cron_expression", current.cron_expression)),
                str(updates.get("timezone", current.timezone)),
            )
        updates["updated_at"] = _now()
        await _write_canonical(current.model_copy(update=updates))
        # Re-read after the await: a tick may have projected newer cursors.
        latest = stores.schedules.get(schedule_id) or current
        updated: Schedule = latest.model_copy(update=updates)
        stores.schedules[schedule_id] = updated
    return updated


async def _delete_canonical(schedule_id: str) -> None:
    from services.scheduler import ScheduleAdmissionUnavailable, delete_canonical_definition

    try:
        await delete_canonical_definition(schedule_id)
    except ScheduleAdmissionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: str, request: Request) -> None:
    await _writable_schedule(request, schedule_id, require_active=False)
    from services.scheduler import definition_lock

    async with definition_lock(schedule_id):
        await _delete_canonical(schedule_id)
        stores.schedules.pop(schedule_id, None)


class ManualFireBody(BaseModel):
    """Optional body of `POST /{id}/run` — the manual fire's stable identity.

    `fire_id` is the occurrence identity of the hand fire (#1120): a caller
    retrying the same logical request sends the same token and reconciles to
    the Run the first call created, instead of minting a second one.  Opaque to
    the server.
    """

    model_config = ConfigDict(extra="ignore")

    fire_id: str | None = None

    _bound = field_validator("fire_id")(_check_fire_id)


@router.post("/{schedule_id}/run", response_model=Schedule)
async def run_schedule(
    schedule_id: str,
    request: Request,
    body: ManualFireBody | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Schedule:
    """Fire the schedule now, for real.

    This used to stamp `last_run` and return — no Run created, no cursor
    advanced, nothing counted against `max_runs`. The schedule then reported a
    fire that no `run_id` anywhere corresponded to, which is the defect #231
    removed from the tick path and missed here.

    A fire that cannot happen is a 409 rather than a silent stamp: the caller
    asked for work to start, and it did not.

    The fire's occurrence identity is the caller's `fire_id` (this body) or
    `Idempotency-Key` header — the standard retry identity (#1120).  Two calls
    carrying the same identity are one logical firing: the retry reconciles to
    the Run the first call created and no second Run exists.  A call carrying
    no identity is its own deliberate firing, with a server-minted token.
    """
    await _writable_schedule(request, schedule_id)
    from services.scheduler import ScheduleAdmissionUnavailable, ScheduleNotFireable, fire_now

    raw = (body.fire_id if body is not None else None) or idempotency_key
    # The header is held to the body's `fire_id` contract (#1120): stripped,
    # opaque, and bounded, because the token becomes durable Run provenance
    # and half of a unique occurrence claim. A blank header is no identity —
    # the server mints one — rather than a 422, matching the absent case.
    try:
        fire_id = _check_fire_id(raw) if raw and raw.strip() else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        await fire_now(schedule_id, fire_id=fire_id)
    except ScheduleNotFireable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ScheduleAdmissionUnavailable as exc:
        # A configured Container missing its admission wiring is a server
        # misconfiguration, not a schedule that cannot fire (#1119): 409 would
        # tell the caller to fix the schedule, when the process is what is
        # broken. 503 says the dependency is not there and the request may be
        # retried once it is.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    fired = stores.schedules.get(schedule_id)
    if fired is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return fired
