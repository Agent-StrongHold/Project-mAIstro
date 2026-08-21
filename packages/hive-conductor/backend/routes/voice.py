from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from models.schemas import ChatCompletionRequest
from pydantic import BaseModel, ConfigDict
from services.chat_completion import run_chat_completion

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])

VOICE_API_KEY = os.environ.get("VOICE_API_KEY", "")


def _verify_key(authorization: str | None) -> None:
    if not VOICE_API_KEY:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="API key required")
    if authorization[7:] != VOICE_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


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
async def voice_intent(
    body: VoiceIntentBody, authorization: str | None = Header(None)
) -> VoiceIntentResponse:
    _verify_key(authorization)

    context_parts = [body.text]
    if body.room:
        context_parts.append(f"(spoken in the {body.room})")
    if body.source:
        context_parts.append(f"(source device: {body.source})")
    if body.person:
        context_parts.append(f"(speaker: {body.person})")

    req = ChatCompletionRequest(
        messages=[
            {"role": "user", "content": " ".join(context_parts)},
        ],
    )

    from adapters.llm_http import HttpOpenAIProtocolLLM
    from config import get_settings
    from services.secrets import litellm_api_key as resolve_litellm_api_key

    settings = get_settings()
    key = resolve_litellm_api_key(settings) or os.environ.get("LITELLM_API_KEY", "")
    base = settings.litellm_api_base or os.environ.get("LITELLM_API_BASE", "")
    if base and key:
        llm = HttpOpenAIProtocolLLM(base_url=base, api_key=key, variant="chat_completions")
        model = settings.chat_default_model or "cerebras-qwen-3-235b-a22b-2507"
    else:
        from services.chat_completion import build_llm_port

        llm = build_llm_port()
        model = req.model or settings.chat_default_model or "cerebras-qwen-3-235b-a22b-2507"

    result = await run_chat_completion(
        req, return_actions=True, skip_summary=True, _llm=llm, _model=model
    )

    actions: list[dict[str, Any]] = result.get("actions", [])
    reply = ""
    intent = "unknown"

    for choice in result.get("choices", []):
        msg = choice.get("message", {})
        reply = msg.get("content", "") or ""

    if actions:
        intent = actions[0].get("tool", "unknown")
    elif reply:
        intent = "conversation"

    logger.info(
        "voice intent: text=%r room=%r intent=%s actions=%d",
        body.text,
        body.room,
        intent,
        len(actions),
    )

    return VoiceIntentResponse(
        understood=bool(reply or actions),
        intent=intent,
        actions_taken=actions,
        reply=reply,
    )
