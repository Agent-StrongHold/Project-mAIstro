from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["voice"])


class VoiceIntentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    source: str = ""
    room: str = ""
    person: str = ""


class VoiceIntentResponse(BaseModel):
    understood: bool
    intent: str
    actions_taken: list[dict[str, Any]]
    reply: str


@router.post("/intent", response_model=VoiceIntentResponse)
async def voice_intent(body: VoiceIntentBody, request: Request) -> VoiceIntentResponse:
    """Fail closed until voice input crosses the canonical Warden boundary (#484)."""
    del body, request
    raise HTTPException(
        status_code=503,
        detail="Conductor model-driven voice is disabled until Warden safety boundaries are active.",
    )
