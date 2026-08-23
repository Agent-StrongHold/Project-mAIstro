from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

import stores
from adapters.task_backend import WORKSPACE_NOT_ROUTABLE_DETAIL, WorkspaceNotRoutable
from fastapi import APIRouter, HTTPException, Request
from models.schemas import Mission, MissionStep
from pydantic import BaseModel, ConfigDict
from services.engine import get_engine
from services.workspace_mode import is_workspace_member

from routes.audit import log_audit

router = APIRouter(tags=["missions"])
logger = logging.getLogger("hive.missions")


def _now() -> datetime:
    return datetime.now(UTC)


def _task_to_mission(rec: object) -> Mission:
    """Convert a TaskRecord from EngineService into a hive Mission."""
    metadata: dict[str, object] = {}
    err = getattr(rec, "error", None)
    if err:
        metadata["error"] = err
    return Mission(
        id=rec.id,  # type: ignore[attr-defined]
        name=rec.name,  # type: ignore[attr-defined]
        description=rec.description,  # type: ignore[attr-defined]
        status=rec.mission_status,  # type: ignore[attr-defined]
        priority="medium",
        created_at=rec.created_at,  # type: ignore[attr-defined]
        updated_at=rec.completed_at or rec.started_at or rec.created_at,  # type: ignore[attr-defined]
        started_at=rec.started_at,  # type: ignore[attr-defined]
        completed_at=rec.completed_at,  # type: ignore[attr-defined]
        progress=rec.progress,  # type: ignore[attr-defined]
        metadata=metadata,
    )


@router.get("", response_model=list[Mission])
def list_missions() -> list[Mission]:
    engine = get_engine()
    if engine.is_configured or engine._backend is not None:
        tasks = engine.list_tasks()
        if tasks:
            return [_task_to_mission(t) for t in tasks]
    return list(stores.missions.values())


class ClearMissionsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str | None = None  # "failed", "completed", or None = all terminal


@router.post("/clear")
def clear_missions(body: ClearMissionsBody) -> dict[str, int]:
    """Remove terminal missions from the in-memory queue (POC cleanup)."""
    engine = get_engine()
    if engine._backend is None:
        return {"removed": 0}
    removed = engine.clear_tasks(status=body.status)
    log_audit("missions_clear", "system", detail={"status": body.status, "removed": removed})
    return {"removed": removed}


@router.get("/{mission_id}", response_model=Mission)
def get_mission(mission_id: str) -> Mission:
    engine = get_engine()
    if engine.is_configured or engine._backend is not None:
        rec = engine.get_task(mission_id)
        if rec is not None:
            return _task_to_mission(rec)
    if mission_id not in stores.missions:
        raise HTTPException(status_code=404, detail="mission not found")
    return stores.missions[mission_id]


@router.get("/{mission_id}/steps", response_model=list[MissionStep])
def get_steps(mission_id: str) -> list[MissionStep]:
    engine = get_engine()
    if engine.is_configured or engine._backend is not None:
        rec = engine.get_task(mission_id)
        if rec is not None:
            # Synthesise step list from current task phase
            step_status = "running" if rec.mission_status == "running" else rec.mission_status  # type: ignore[attr-defined]
            step: MissionStep | None = None
            current = rec.current_step  # type: ignore[attr-defined]
            if current:
                step = MissionStep(
                    id=f"{mission_id}-step-1",
                    mission_id=mission_id,
                    name=current,
                    description=current,
                    status=step_status,
                    order=1,
                )
            return [step] if step else []
    return list(stores.mission_steps.get(mission_id, []))


class CreateMissionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    priority: str = "medium"
    assigned_agents: list[str] = []


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("id") or user.get("username") or "dev")


@router.post("", response_model=Mission)
async def create_mission(
    body: CreateMissionBody, request: Request, workspace_id: str | None = None
) -> Mission:
    """Create a mission, optionally scoped to one of the caller's workspaces.

    `workspace_id` decides which Workspace's Root Project the canonical Run is
    filed in (#158). Omitted -- every caller before this parameter existed --
    keeps the old behaviour: the deployment's default Workspace, named
    explicitly by `AgentConfig.workspace_id` rather than inferred.
    """
    if workspace_id and not is_workspace_member(_user_id(request), workspace_id):
        raise HTTPException(status_code=403, detail="only a workspace member can submit work to it")
    engine = get_engine()
    if engine.is_configured or engine._backend is not None:
        try:
            rec = await engine.submit_task(
                body.name, body.description or body.name, workspace_id=workspace_id
            )
        except WorkspaceNotRoutable as exc:
            # 501, not 500: the request is well-formed and authorized, and this
            # deployment simply cannot honour it. The exception text names the
            # server it would have gone to, which belongs in the log and not in
            # a response body.
            logger.warning("workspace_not_routable %s", exc)
            raise HTTPException(status_code=501, detail=WORKSPACE_NOT_ROUTABLE_DETAIL) from exc
        log_audit("mission_create", "system", target=rec.id, detail={"name": body.name})
        return _task_to_mission(rec)

    # Fallback: in-memory stub (dev mode without maistro-core)
    mid = str(uuid4())[:12]
    t = _now()
    m = Mission(
        id=mid,
        name=body.name,
        description=body.description or body.name,
        status="pending",
        priority=body.priority,
        created_at=t,
        updated_at=t,
        progress=0.0,
        steps_total=0,
        steps_completed=0,
        assigned_agents=body.assigned_agents,
    )
    stores.missions[mid] = m
    stores.mission_steps[mid] = []
    log_audit("mission_create", "system", target=mid, detail={"name": body.name})
    return m


class UpdateMissionStatusBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


@router.patch("/{mission_id}/status", response_model=Mission)
def update_mission_status(
    mission_id: str,
    body: UpdateMissionStatusBody,
    request: Request,
) -> Mission:
    engine = get_engine()
    if engine._backend is not None:
        rec = engine.get_task(mission_id)
        if rec is not None:
            # Maistro task runner owns lifecycle; UI status buttons are legacy stubs only.
            raise HTTPException(
                status_code=409,
                detail=(
                    "Engine-backed mission — status is read-only. "
                    "Delete it or invoke a new task from Program / Agent Fleet."
                ),
            )

    if mission_id not in stores.missions:
        raise HTTPException(status_code=404, detail="mission not found")
    m = stores.missions[mission_id]
    m.status = body.status  # type: ignore[assignment]
    m.updated_at = _now()
    if body.status in _TERMINAL_STATUSES:
        m.completed_at = _now()
        m.progress = 1.0 if body.status == "completed" else m.progress
        _revoke_task_elevation(request, mission_id)
    stores.missions[mission_id] = m
    log_audit("mission_status", "system", target=mission_id, detail={"status": body.status})
    return m


def _revoke_task_elevation(request: Request, task_id: str) -> None:
    session_id = request.cookies.get("hive_session")
    if not session_id:
        return
    try:
        from routes.auth import revoke_task_elevation

        revoke_task_elevation(session_id, task_id)
    except Exception as _exc:
        __import__("logging").getLogger("hive.routes.missions").warning(
            "error_swallowed file=%s line=%d: %s",
            "packages/hive-conductor/backend/routes/missions.py",
            193,
            _exc,
        )
        pass


@router.delete("/{mission_id}", status_code=204)
def delete_mission(mission_id: str, request: Request) -> None:
    engine = get_engine()
    if engine._backend is not None:
        if not engine.delete_task(mission_id):
            raise HTTPException(
                status_code=404,
                detail="Mission not found or still running (only completed/failed can be deleted)",
            )
        _revoke_task_elevation(request, mission_id)
        log_audit("mission_delete", "system", target=mission_id)
        return
    if mission_id not in stores.missions:
        raise HTTPException(status_code=404, detail="mission not found")
    stores.missions.pop(mission_id, None)
    stores.mission_steps.pop(mission_id, None)
    log_audit("mission_delete", "system", target=mission_id)


class MissionGuidanceBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str


@router.post("/{mission_id}/guidance")
async def post_mission_guidance(
    mission_id: str,
    body: MissionGuidanceBody,
    request: Request,
) -> dict[str, object]:
    """Human guidance on a mission — feeds the meta hyperagent."""
    from services.program_hyperagent import (
        apply_guidance_and_pulse,
        require_pm_poc,
        user_id_from_request,
    )

    require_pm_poc()
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Guidance text required")

    uid = user_id_from_request(request)
    log_audit("mission_guidance", uid, target=mission_id, detail={"chars": len(body.text)})
    result = await apply_guidance_and_pulse(uid, body.text.strip())
    return {"ok": True, "mission_id": mission_id, **result}
