"""Live chat with TuringActor / TuringChatSession.

POST a message and get Turing's reply. Uses the real TuringChatSession from
maistro_turing.runtime, wired through the state singleton's bridges.

GAP: sessions are held in an in-memory dict keyed by an opaque session id. The
TuringProviderBridge in TuringState has no LLM client configured, so
TuringChatSession.handle_message() would raise RuntimeError("no LLM client
configured") on a real call. We therefore guard for that and return a clear
503 in dev rather than a 500. Production wiring injects a real LLMClient into the
provider bridge (via maistro.container) and this guard becomes dead code.

Streaming is not implemented: the underlying TuringChatSession exposes only a
non-streaming handle_message(). A streaming endpoint would need a token-yielding
method on the runtime, which does not exist yet — left as a TODO so the contract
isn't faked.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from maistro_turing.runtime import TuringChatSession

from ..middleware.auth import require_user
from ..state import get_state

router = APIRouter(tags=["chat"])

# (user_id, session_id) -> TuringChatSession. Lives for the process; a
# production version persists history through the memory bridge. Keying by
# user_id too prevents one authenticated caller from attaching to another
# user's session (and its prior _history) by reusing/guessing a session id.
_SESSIONS: dict[tuple[str, str], TuringChatSession] = {}


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str
    session_id: str | None = None


@router.post("")
async def chat(body: ChatBody, user: dict = Depends(require_user)) -> dict:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    session_id = body.session_id or str(uuid4())
    key = (user["id"], session_id)
    session = _SESSIONS.get(key)
    if session is None:
        session = get_state().new_chat_session()
        _SESSIONS[key] = session

    try:
        reply = await session.handle_message(message)
    except RuntimeError as exc:
        # No LLM client configured in the dev provider bridge — see module GAP.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"session_id": session_id, "reply": reply}
