"""Phase 7 — Topology comparison endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from hive_conductor.services.topology_compare import ALLOWED_GROUP_FIELDS, compare_variants

router = APIRouter(tags=["topology"])


@router.get("/{dag_id}/compare")
async def compare(
    dag_id: str,
    request: Request,
    group_by: str = "model_used",
    window_seconds: int = 24 * 3600,
) -> dict[str, Any]:
    try:
        return await compare_variants(
            dag_id,
            group_by=group_by,
            window_seconds=window_seconds,
            org_id=str(getattr(request.state, "org_id", "") or ""),
            project_id=str(getattr(request.state, "project_id", "") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/group-fields")
def allowed_group_fields() -> list[str]:
    return list(ALLOWED_GROUP_FIELDS)
