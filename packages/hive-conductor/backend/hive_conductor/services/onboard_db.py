"""Persistent storage via Launch PostgreSQL (PostgREST interface)."""

import os
from datetime import UTC

import httpx

from maistro.http import shared_client

POSTGREST_URL = (
    os.environ.get("POSTGREST_URL") or os.environ.get("DEPLOY_TARGET_POSTGREST_URL") or ""
)


async def _req(method: str, table: str, **kwargs) -> httpx.Response:
    async with shared_client(base_url=POSTGREST_URL, timeout=10) as c:
        return await getattr(c, method)(f"/{table}", **kwargs)


# ─── Projects ───


async def create_project(data: dict) -> dict:
    r = await _req(
        "post", "onboard_projects", json=data, headers={"Prefer": "return=representation"}
    )
    r.raise_for_status()
    return r.json()[0]


async def list_projects(user_id: str) -> list[dict]:
    r = await _req(
        "get",
        "onboard_projects",
        params={"user_id": f"eq.{user_id}", "deleted_at": "is.null", "order": "created_at.desc"},
    )
    r.raise_for_status()
    return r.json()


async def get_project(project_id: str) -> dict | None:
    r = await _req(
        "get", "onboard_projects", params={"id": f"eq.{project_id}", "deleted_at": "is.null"}
    )
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


async def update_project(project_id: str, data: dict) -> None:
    await _req("patch", "onboard_projects", json=data, params={"id": f"eq.{project_id}"})


async def delete_project(project_id: str) -> None:
    from datetime import datetime

    await update_project(project_id, {"deleted_at": datetime.now(UTC).isoformat()})


# ─── Scans ───


async def create_scan(data: dict) -> dict:
    r = await _req(
        "post", "onboard_scan_results", json=data, headers={"Prefer": "return=representation"}
    )
    r.raise_for_status()
    return r.json()[0]


async def get_latest_scan(project_id: str) -> dict | None:
    r = await _req(
        "get",
        "onboard_scan_results",
        params={"project_id": f"eq.{project_id}", "order": "started_at.desc", "limit": "1"},
    )
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


async def update_scan(scan_id: str, data: dict) -> None:
    await _req("patch", "onboard_scan_results", json=data, params={"id": f"eq.{scan_id}"})


# ─── Deployments ───


async def create_deployment(data: dict) -> dict:
    r = await _req(
        "post", "onboard_deployments", json=data, headers={"Prefer": "return=representation"}
    )
    r.raise_for_status()
    return r.json()[0]


async def get_deployment_by_tork_job(tork_job_id: str) -> dict | None:
    r = await _req("get", "onboard_deployments", params={"tork_job_id": f"eq.{tork_job_id}"})
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


async def update_deployment(dep_id: str, data: dict) -> None:
    await _req("patch", "onboard_deployments", json=data, params={"id": f"eq.{dep_id}"})
