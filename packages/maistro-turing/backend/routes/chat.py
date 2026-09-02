"""Live chat with TuringActor / TuringChatSession.

POST a message and get Turing's reply. The reachable request is admitted and
executed through the canonical Workspace/Project/Run/NodeRun/Attempt spine;
``TuringChatSession`` remains the owner of conversation-domain behavior.

The standalone backend currently composes the canonical in-memory stores in
``backend.execution`` because the rest of this service is explicitly
process-local. It does not claim that ``maistro.container`` injects Turing
bridges: there is no such wiring on the current product path. A durable product
composition can replace the store implementations through the same public
contracts without changing the chat node.

Streaming is not implemented: the underlying TuringChatSession exposes only a
non-streaming handle_message(). A streaming endpoint would need a token-yielding
method on the runtime, which does not exist yet — left as a TODO so the contract
isn't faked.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from maistro.graph.durable_runs import DurableRunRecord
from maistro.runs.model import RunStatus
from maistro_turing.runtime import TuringChatSession

from ..execution import TuringAdmissionUnavailable, get_execution_plane
from ..middleware.auth import require_user
from ..state import get_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_PUBLIC_CHAT_FAILURE = "Turing chat execution failed"

# (user_id, session_id) -> TuringChatSession. Lives for the process; a
# production version persists history through the memory bridge. Keying by
# user_id too prevents one authenticated caller from attaching to another
# user's session (and its prior _history) by reusing/guessing a session id.
_SESSIONS: dict[tuple[str, str], TuringChatSession] = {}


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str
    session_id: str | None = None


def _reply_from_record(record: DurableRunRecord) -> str:
    if not record.node_runs:
        raise RuntimeError("canonical Turing chat Run produced no NodeRun")
    result = record.node_runs[-1].result
    if not isinstance(result, dict) or "reply" not in result:
        raise RuntimeError("canonical Turing chat NodeRun produced no reply")
    return str(result["reply"])


async def _unrecorded_reply(session: TuringChatSession, message: str) -> str:
    """Preserve chat availability when only canonical audit admission failed."""
    try:
        return await session.handle_message(message)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("unrecorded Turing chat execution failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail=_PUBLIC_CHAT_FAILURE) from exc


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
        record = await get_execution_plane().run_chat(
            session=session,
            user_id=str(user["id"]),
            session_id=session_id,
            message=message,
        )
    except TuringAdmissionUnavailable:
        logger.warning(
            "Turing chat audit admission unavailable; executing turn without run_id",
            exc_info=True,
        )
        reply = await _unrecorded_reply(session, message)
        return {"session_id": session_id, "run_id": None, "reply": reply}

    if record.run.status is not RunStatus.COMPLETED:
        logger.warning(
            "canonical Turing chat Run %s failed: %s",
            record.run_id,
            record.run.error,
        )
        raise HTTPException(status_code=503, detail=_PUBLIC_CHAT_FAILURE)

    try:
        reply = _reply_from_record(record)
    except RuntimeError as exc:
        logger.warning("canonical Turing chat result projection failed", exc_info=True)
        raise HTTPException(status_code=503, detail=_PUBLIC_CHAT_FAILURE) from exc

    return {"session_id": session_id, "run_id": record.run_id, "reply": reply}
