from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Request
from models.schemas import ChatCompletionRequest
from pydantic import BaseModel, ConfigDict
from services.chat_completion import build_llm_port, conversation_only

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])


class VoiceIntentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    source: str = ""
    room: str = ""
    person: str = ""


class VoiceIntentResponse(BaseModel):
    """What a contained voice turn can actually report (#440).

    `actions_taken` used to sit here as a `list[dict]` of the tools the
    utterance invoked. Nothing could ever put anything in it: the route sends
    `tools=None`, so no tool call is ever offered, let alone executed. It was
    removed rather than left empty, because a field that is structurally
    unpopulatable is a completion claim nothing derives from evidence (#31),
    and a caller cannot tell "no tools ran" from "we forgot to record them".

    `intent` is narrowed to the two values the service can distinguish. It was
    documented as naming the first tool invoked, which it has never done. The
    two remaining values report whether the model said anything, which is the
    only classification available while tools are contained.

    Restoring a real action record is #315's, together with the Warden
    input/tool-result/output boundary that has to gate the tools before any of
    them may run again. That is a security boundary, not a response field, so
    it is not smuggled in here.
    """

    understood: bool
    intent: Literal["conversation", "unknown"]
    reply: str


@router.post("/intent", response_model=VoiceIntentResponse)
async def voice_intent(body: VoiceIntentBody, request: Request) -> VoiceIntentResponse:
    """Answer a spoken utterance conversationally, on the chat path's own seam.

    M0 containment (#484): AuthMiddleware still resolves the device/account
    principal, but the utterance is answered without the model-driven tool loop.

    The request is built through `conversation_only`, the same trust boundary
    `/v1/chat/complete` and `/v1/chat/stream` pass their requests through, and
    the port comes from `build_llm_port`, the same builder they use. Voice
    previously constructed an `HttpOpenAIProtocolLLM` itself and diverged from
    that builder in three ways -- a hard-coded HTTP variant rather than the
    configured one, `LITELLM_API_KEY` rather than `LITELLM_PROXY_KEY`, and its
    own model-default chain. A second execution path is how the containment
    rule ends up meaning something different on the route nobody looks at.
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

    req = conversation_only(
        ChatCompletionRequest(messages=[{"role": "user", "content": " ".join(context_parts)}])
    )

    result = await build_llm_port().complete(req)

    reply = ""
    for choice in result.get("choices", []):
        reply = (choice.get("message", {}) or {}).get("content", "") or ""

    intent: Literal["conversation", "unknown"] = "conversation" if reply else "unknown"

    logger.info(
        "voice intent: user=%s room=%r intent=%s",
        user_id or "unknown",
        body.room,
        intent,
    )

    return VoiceIntentResponse(understood=bool(reply), intent=intent, reply=reply)
