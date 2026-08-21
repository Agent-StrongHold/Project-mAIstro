"""Project onboarding routes: intake → scan → deploy. Persistent via Launch DB/Cache/Store."""

import json
import os
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from services import onboard_db, pipeline_orchestrator, repo_scanner

router = APIRouter(prefix="/v1/projects", tags=["projects"])

CACHE_URL = os.environ.get("REDIS_URL") or os.environ.get("DEPLOY_TARGET_CACHE_URL") or ""


# ─── Models ───


class ProjectCreate(BaseModel):
    repo_url: str
    branch: str = "main"
    name: str | None = None
    dockerfile_path: str = "Dockerfile"

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        if not re.match(r"^(git@|https?://)", v):
            raise ValueError("repo_url must start with git@ or http(s)://")
        return v


class DeployTrigger(BaseModel):
    skip_scan: bool = False
    force: bool = False


def _user_id(request: Request) -> str:
    return getattr(request.state, "user_id", None) or request.headers.get("x-user-id", "anonymous")


def _derive_name(repo_url: str) -> str:
    return repo_url.rstrip("/").split("/")[-1].removesuffix(".git")


async def _publish_event(project_id: str, event: str, data: dict | None = None):
    """Publish pipeline event to Redis for SSE streaming."""
    data = data if data is not None else {}
    if not CACHE_URL:
        return
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(CACHE_URL)
        payload = json.dumps(
            {
                "event": event,
                "project_id": project_id,
                "data": data,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        await r.publish(f"project:{project_id}:events", payload)
        await r.aclose()
    except Exception:
        pass


# ─── Routes ───


@router.post("", status_code=201)
async def create_project(body: ProjectCreate, request: Request):
    uid = _user_id(request)
    name = body.name or _derive_name(body.repo_url)
    project = await onboard_db.create_project(
        {
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "name": name,
            "repo_url": body.repo_url,
            "branch": body.branch,
            "dockerfile_path": body.dockerfile_path,
            "status": "created",
        }
    )
    return project


@router.get("")
async def list_projects(request: Request):
    return await onboard_db.list_projects(_user_id(request))


@router.get("/{project_id}")
async def get_project(project_id: str, request: Request):
    p = await onboard_db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    if p["user_id"] != _user_id(request):
        raise HTTPException(403)
    return p


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, request: Request):
    p = await onboard_db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    if p["user_id"] != _user_id(request):
        raise HTTPException(403)
    await onboard_db.delete_project(project_id)


@router.post("/{project_id}/scan", status_code=202)
async def trigger_scan(project_id: str, request: Request, background_tasks: BackgroundTasks):
    p = await onboard_db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    if p["user_id"] != _user_id(request):
        raise HTTPException(403)
    await onboard_db.update_project(project_id, {"status": "scanning"})
    scan = await onboard_db.create_scan(
        {"id": str(uuid.uuid4()), "project_id": project_id, "status": "running"}
    )
    background_tasks.add_task(_run_scan, project_id, scan["id"], p["repo_url"], p["branch"])
    await _publish_event(project_id, "scan_started")
    return {"scan_id": scan["id"], "status": "running"}


async def _run_scan(project_id: str, scan_id: str, repo_url: str, branch: str):
    result = await repo_scanner.scan_repo(repo_url, branch)
    status = "error" if result.get("error") else result.get("status", "passed")
    await onboard_db.update_scan(
        scan_id,
        {
            "status": status,
            "findings": json.dumps(result["findings"]),
            "summary": json.dumps(result["summary"]),
            "completed_at": datetime.now(UTC).isoformat(),
            "error": result.get("error"),
        },
    )
    new_status = "scan_passed" if status != "error" else "scan_failed"
    await onboard_db.update_project(project_id, {"status": new_status})
    await _publish_event(
        project_id, "scan_complete", {"status": new_status, "findings": len(result["findings"])}
    )


@router.get("/{project_id}/scan")
async def get_scan(project_id: str, request: Request):
    p = await onboard_db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    if p["user_id"] != _user_id(request):
        raise HTTPException(403)
    scan = await onboard_db.get_latest_scan(project_id)
    if not scan:
        raise HTTPException(404, "No scan results")
    return scan


@router.post("/{project_id}/deploy", status_code=202)
async def trigger_deploy(project_id: str, body: DeployTrigger, request: Request):
    p = await onboard_db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    if p["user_id"] != _user_id(request):
        raise HTTPException(403)

    scan = await onboard_db.get_latest_scan(project_id)
    summary = json.loads(scan["summary"]) if scan and scan.get("summary") else None

    try:
        result = await pipeline_orchestrator.trigger_deploy(
            project_id=project_id,
            repo_url=p["repo_url"],
            branch=p["branch"],
            dockerfile_path=p["dockerfile_path"],
            scan_summary=summary,
            force=body.force,
        )
    except Exception as e:
        raise HTTPException(400, str(e)) from e

    dep = await onboard_db.create_deployment(
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "status": "building",
            "tork_job_id": result["tork_job_id"],
            "scan_result_id": scan["id"] if scan else None,
        }
    )
    await onboard_db.update_project(project_id, {"status": "building"})
    await _publish_event(project_id, "build_started", {"tork_job_id": result["tork_job_id"]})
    return {"deployment_id": dep["id"], **result}


@router.post("/webhooks/external-build")
async def external_build_webhook(request: Request):
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {os.environ.get('EXTERNAL_BUILD_CALLBACK_TOKEN', 'callback-token')}"
    if auth != expected:
        raise HTTPException(401)

    payload = await request.json()
    state = payload.get("state", "")
    job_id = payload.get("id", "")

    dep = await onboard_db.get_deployment_by_tork_job(job_id)
    if not dep:
        return {"ok": True}

    if state == "COMPLETED":
        await onboard_db.update_deployment(dep["id"], {"status": "deploying"})
        p = await onboard_db.get_project(dep["project_id"])
        if p:
            await _publish_event(dep["project_id"], "build_complete")
            try:
                result = await pipeline_orchestrator.deploy_to_launch(
                    p["name"], p["repo_url"], p["branch"]
                )
                await onboard_db.update_project(
                    dep["project_id"],
                    {
                        "status": "live",
                        "launch_url": result["url"],
                        "launch_app_name": result["app_name"],
                    },
                )
                await onboard_db.update_deployment(
                    dep["id"],
                    {
                        "status": "live",
                        "launch_url": result["url"],
                        "completed_at": datetime.now(UTC).isoformat(),
                    },
                )
                await _publish_event(dep["project_id"], "deploy_complete", {"url": result["url"]})
            except Exception as e:
                await onboard_db.update_project(dep["project_id"], {"status": "deploy_failed"})
                await onboard_db.update_deployment(dep["id"], {"status": "failed", "error": str(e)})
                await _publish_event(dep["project_id"], "deploy_failed", {"error": str(e)})
    elif state == "FAILED":
        await onboard_db.update_deployment(
            dep["id"], {"status": "failed", "error": "external build job failed"}
        )
        await onboard_db.update_project(dep["project_id"], {"status": "build_failed"})
        await _publish_event(dep["project_id"], "build_failed")

    return {"ok": True}


@router.get("/{project_id}/events")
async def project_events(project_id: str, request: Request):
    """SSE endpoint — streams pipeline events from Redis pub/sub."""
    p = await onboard_db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    if p["user_id"] != _user_id(request):
        raise HTTPException(403)

    async def event_stream():
        if not CACHE_URL:
            yield 'data: {"event": "error", "message": "no cache configured"}\n\n'
            return
        import redis.asyncio as aioredis

        r = aioredis.from_url(CACHE_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"project:{project_id}:events")
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    yield f"data: {msg['data'].decode()}\n\n"
        finally:
            await pubsub.unsubscribe()
            await r.aclose()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
