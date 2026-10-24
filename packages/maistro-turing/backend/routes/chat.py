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

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from maistro.graph.durable_runs import DurableRunRecord
from maistro.identity import Principal
from maistro.runs.model import RunStatus

from ..execution import TuringAdmissionUnavailable, get_execution_plane
from ..middleware.auth import require_user
from ..security import TuringSecurityContext
from ..state import get_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_PUBLIC_CHAT_FAILURE = "Turing chat execution failed"

# Sessions live in the composed state's bounded, workspace-owned registry
# (#859): keyed by the canonical Workspace resolved for the authenticated
# principal plus the client-supplied session id, TTL- and cardinality-bounded,
# and disposable. The client id selects a conversation inside the caller's
# scope; it never decides ownership, and guessing another user's id yields an
# isolated fresh session in the guesser's own scope.


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


@router.post("")
async def chat(
    body: ChatBody,
    request: Request,
    user: Principal = Depends(require_user),
) -> dict:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    session_id = body.session_id or str(uuid4())
    plane = get_execution_plane()
    st = get_state()
    workspace_id, project_id = await plane.scope_for(user.user_id)
    try:
        session = st.sessions.resolve(
            workspace_id=workspace_id,
            session_id=session_id,
            # The factory binds the caller's resolved scope, so the session's
            # episodic chat capture persists with the caller's provenance
            # instead of blank user/project fields (#859).
            factory=lambda: st.new_chat_session(
                user_id=user.user_id,
                workspace_id=workspace_id,
                project_id=project_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        record = await plane.run_chat(
            session=session,
            user_id=user.user_id,
            session_id=session_id,
            message=message,
        )
    except TuringAdmissionUnavailable as exc:
        # Admission is the security boundary for the canonical execution
        # spine. Never dispatch a turn when its Run evidence is unavailable.
        logger.warning("Turing chat canonical admission unavailable", exc_info=True)
        raise HTTPException(status_code=503, detail=_PUBLIC_CHAT_FAILURE) from exc

    # The middleware scans before Run admission, but chat audit correlation is
    # deferred until the canonical Run supplies Workspace/Project/Run identity.
    # This also records the ingress verdict when execution later fails.
    inbound_verdict = getattr(request.state, "turing_inbound_verdict", None)
    if inbound_verdict is not None:
        try:
            root = await plane.project_store.root_for_workspace(record.run.workspace_id)
            await get_state().inbound_security.audit_verdict(
                inbound_verdict,
                message,
                boundary="user_input",
                context=TuringSecurityContext(
                    principal=user.user_id,
                    route="/v1/chat",
                    action="chat",
                    workspace_id=record.run.workspace_id,
                    project_id=root.project_id,
                    run_id=record.run_id,
                ),
            )
        except Exception as exc:
            logger.warning("canonical Turing chat security audit failed", exc_info=True)
            raise HTTPException(status_code=503, detail=_PUBLIC_CHAT_FAILURE) from exc

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
