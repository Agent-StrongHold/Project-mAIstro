from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from models.schemas import ChatCompletionRequest
from pydantic import BaseModel, ConfigDict
from services.chat_completion import run_chat_completion

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
    """Turn a spoken utterance into tool calls, as the account behind the device.

    There is no key check here any more, and that is the fix rather than an
    omission: `AuthMiddleware` refuses this path without a principal, and the
    route's own check could not do that job — it was read once at import and
    returned early when unset, which was the shipped default. What arrives here
    is a real account, and it is passed down so the tool loop authorises against
    a person instead of running anonymously.
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

    # `return_actions`, `skip_summary` and `_model` are not parameters of
    # `run_chat_completion` and never have been in this repository's history,
    # so this call raised TypeError on every request: the route has never
    # worked. That is not why it is being changed -- a route that happens to
    # crash is not an authorization control, which is the whole point of #316 --
    # but leaving a call that cannot succeed in a file this change touches would
    # be worse than the crash.
    #
    # The consequence is honest rather than hidden: the service exposes no list
    # of tool calls it made, so `actions_taken` is empty and `intent` can only
    # distinguish "it said something" from "it did not". Restoring the action
    # list is a product change with its own issue, not something to smuggle in
    # behind a security fix.
    req.model = model
    result = await run_chat_completion(req, user_id=user_id, _llm=llm)

    actions: list[dict[str, Any]] = []
    reply = ""

    for choice in result.get("choices", []):
        msg = choice.get("message", {})
        reply = msg.get("content", "") or ""

    intent = "conversation" if reply else "unknown"

    # The utterance itself is not logged: it is user speech, and a voice
    # satellite hears more than it is addressed with. Room, intent and action
    # count are what an operator needs to tell a working device from a broken
    # one.
    logger.info(
        "voice intent: user=%s room=%r intent=%s actions=%d",
        user_id or "unknown",
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
