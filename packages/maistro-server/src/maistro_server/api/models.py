"""GET /v1/models — expose Maistro tiers as OpenAI-compatible model list.

Open WebUI reads this endpoint to populate its model selector dropdown.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from maistro_server.api.auth import RequireAuth

router = APIRouter(prefix="/v1", tags=["openai-compat"])


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "maistro"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


TIER_MODELS = [
    ModelInfo(id="maistro-tier-1", created=int(time.time()), owned_by="maistro"),
    ModelInfo(id="maistro-tier-2", created=int(time.time()), owned_by="maistro"),
    ModelInfo(id="maistro-tier-3", created=int(time.time()), owned_by="maistro"),
    ModelInfo(id="maistro-tier-4", created=int(time.time()), owned_by="maistro"),
]


@router.get("/models")
async def list_models(_auth: RequireAuth) -> ModelList:
    return ModelList(data=TIER_MODELS)
