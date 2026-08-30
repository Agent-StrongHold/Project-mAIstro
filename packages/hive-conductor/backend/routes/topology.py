"""Phase 7 — Topology comparison endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from services.topology_compare import ALLOWED_GROUP_FIELDS, compare_variants

router = APIRouter(tags=["topology"])


@router.get("/{dag_id}/compare")
async def compare(
    dag_id: str,
    group_by: str = "model_used",
    window_seconds: int = 24 * 3600,
) -> dict[str, Any]:
    try:
        return await compare_variants(
            dag_id,
            group_by=group_by,
            window_seconds=window_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/group-fields")
def allowed_group_fields() -> list[str]:
    return list(ALLOWED_GROUP_FIELDS)
