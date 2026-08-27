from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from models.schemas import ChatCompletionRequest
from pydantic import BaseModel, ConfigDict
from services.chat_completion import build_llm_port

logger = logging.getLogger(__name__)

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
    """Answer a spoken utterance conversationally without model-driven tools.

    M0 containment (#484): AuthMiddleware still resolves the device/account
    principal, but the utterance is sent directly to the LLM rather than through
    the real-tool agent loop. Full Warden input/tool-result/output gating and
    action provenance remain in M2 #315.
    """
    user = getattr(request.state, "user", None) or {}
    user_id = str(user.get("id", ""))

    context_parts = [body.text]
    if body.room:
        context_parts.append(f"(spoken in the {body.room})")
    if body.source:
        context_parts.append(f"(source device: {body.source})")
    if body.person:
        context_parts.append(f"(speaker: {body.person})")

    req = ChatCompletionRequest(
        messages=[{"role": "user", "content": " ".join(context_parts)}],
        tools=None,
    )

    from adapters.llm_http import HttpOpenAIProtocolLLM
    from config import get_settings
    from services.secrets import litellm_api_key as resolve_litellm_api_key

    settings = get_settings()
    key = resolve_litellm_api_key(settings) or os.environ.get("LITELLM_API_KEY", "")
    base = settings.litellm_api_base or os.environ.get("LITELLM_API_BASE", "")
    if base and key:
        llm = HttpOpenAIProtocolLLM(base_url=base, api_key=key, variant="chat_completions")
        req.model = settings.chat_default_model or "cerebras-qwen-3-235b-a22b-2507"
    else:
        llm = build_llm_port()
        req.model = req.model or settings.chat_default_model or "cerebras-qwen-3-235b-a22b-2507"

    result = await llm.complete(req)

    actions: list[dict[str, Any]] = []
    reply = ""
    for choice in result.get("choices", []):
        msg = choice.get("message", {})
        reply = msg.get("content", "") or ""

    intent = "conversation" if reply else "unknown"

    logger.info(
        "voice intent: user=%s room=%r intent=%s actions=%d",
        user_id or "unknown",
        body.room,
        intent,
        len(actions),
    )

    return VoiceIntentResponse(
        understood=bool(reply),
        intent=intent,
        actions_taken=actions,
        reply=reply,
    )
