"""Phase 5 — Signal #4: thumbs feedback endpoints.

Two routes:

    POST /v1/dag-runs/{run_id}/feedback
    POST /v1/dag-runs/{run_id}/nodes/{node_id}/feedback

Both accept `{ "thumb": "up" | "down", "comment": str?, "project_id": str? }`
and record the signal to outcome_store. The per-node form sets the node_id
on the Outcome so the optimizer can localize the feedback to a specific
node kind. project_id defaults to the user's active project (cookie /
session); if not present, the signal is recorded with empty project_id
and will only surface in cross-project queries.

Auth: requires the logged-in user (AuthMiddleware sets request.state.user).
The user_id from the session is the actor; cross-user writes are
impossible because the route never accepts user_id from the body.

Audit: every submission writes an audit_log entry under action
"dag_feedback" with the run_id + node_id + thumb in `detail`.

Boy Scout / IRON: every branch in this module is covered by
tests/test_feedback_route.py.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from services.feedback_service import ALLOWED_THUMBS, record_thumb

from routes.audit import log_audit

router = APIRouter(tags=["dag-feedback"])


class FeedbackBody(BaseModel):
    thumb: Literal["up", "down"]
    comment: str = Field(default="", max_length=2000)
    # Optional explicit project scope. If absent the route falls back to
    # the user's session-active project (set by the project picker UI).
    project_id: str = ""
    # Optional: when the user knows what saved DAG this run came from, the
    # optimizer fan-in by DAG (not just run) benefits.
    dag_id: str = ""
    # The kind/role for task_type — defaults to "dag_run" in the service.
    task_type: str = ""


def _resolve_user_id(request: Request) -> str:
    """Pull the logged-in user_id out of request.state — set by AuthMiddleware.

    Raises 401 if missing (defensive — AuthMiddleware already protects
    the path so this should be impossible in practice, but the assert
    keeps the contract explicit + tested)."""
    user = getattr(request.state, "user", None)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user["id"])


def _resolve_project_id(request: Request, body: FeedbackBody) -> str:
    """Body wins; otherwise fall back to the session-active project.

    The session-active project is set in `request.state.project_id` by
    the ProjectMiddleware (when present); we use getattr to keep this
    route working before that middleware lands.
    """
    if body.project_id:
        return body.project_id
    return str(getattr(request.state, "project_id", "") or "")


async def _record_feedback(
    request: Request,
    *,
    run_id: str,
    node_id: str,
    body: FeedbackBody,
) -> dict[str, Any]:
    if body.thumb not in ALLOWED_THUMBS:
        # Pydantic enforces this at parse time, but keep the runtime
        # check so direct service-layer callers can't bypass.
        raise HTTPException(status_code=400, detail=f"thumb must be one of {ALLOWED_THUMBS!r}")

    user_id = _resolve_user_id(request)
    project_id = _resolve_project_id(request, body)

    try:
        result = await record_thumb(
            user_id=user_id,
            project_id=project_id,
            run_id=run_id,
            thumb=body.thumb,
            comment=body.comment,
            node_id=node_id,
            dag_id=body.dag_id,
            task_type=body.task_type or "dag_run",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    log_audit(
        action="dag_feedback",
        actor=user_id,
        target=run_id,
        detail={
            "thumb": body.thumb,
            "node_id": node_id,
            "project_id": project_id,
            "dag_id": body.dag_id,
            "outcome_id": result.get("outcome_id"),
            # The comment body itself is NOT logged in plaintext — it may
            # carry user-provided free text that the audit log shouldn't
            # carry forever. Length only for forensic purposes.
            "comment_len": len(body.comment),
        },
        severity="info",
    )

    return result


@router.post("/{run_id}/feedback")
async def submit_run_feedback(
    run_id: str,
    body: FeedbackBody,
    request: Request,
) -> dict[str, Any]:
    """Run-level thumbs. The Outcome's node_id is empty so the signal
    aggregates across all nodes in the run."""
    return await _record_feedback(request, run_id=run_id, node_id="", body=body)


@router.post("/{run_id}/nodes/{node_id}/feedback")
async def submit_node_feedback(
    run_id: str,
    node_id: str,
    body: FeedbackBody,
    request: Request,
) -> dict[str, Any]:
    """Per-node thumbs. The Outcome's node_id is set so the optimizer
    can localize the feedback to one node when proposing topology
    mutations."""
    if not node_id:
        # FastAPI's path parser already rejects empty path segments, but
        # we keep the explicit check so the service contract is
        # documentable + tested.
        raise HTTPException(status_code=400, detail="node_id is required")
    return await _record_feedback(request, run_id=run_id, node_id=node_id, body=body)
