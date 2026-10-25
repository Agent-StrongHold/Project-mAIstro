from __future__ import annotations

from typing import Any

import stores
from fastapi import APIRouter

router = APIRouter(tags=["cli"])


@router.get("/sessions", response_model=list[dict[str, Any]])
def list_cli_sessions() -> list[dict[str, Any]]:
    if not stores.cli_sessions:
        stores.cli_sessions["default"] = {"id": "default", "cwd": "/", "history": []}
    return list(stores.cli_sessions.values())


@router.post("/sessions", response_model=dict[str, Any])
def create_cli_session() -> dict[str, Any]:
    import uuid

    sid = str(uuid.uuid4())[:8]
    rec = {"id": sid, "cwd": "/", "history": []}
    stores.cli_sessions[sid] = rec
    return rec
