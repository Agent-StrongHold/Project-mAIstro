"""Phase 5 — Signal #4: thumbs feedback endpoints.

Two routes:

    POST /v1/dag-runs/{run_id}/feedback
    POST /v1/dag-runs/{run_id}/nodes/{node_id}/feedback

Both accept `{ "thumb": "up" | "down", "comment": str?, "project_id": str? }`
and record the signal to outcome_store. The per-node form sets the node_id
on the Outcome so the optimizer can localize the feedback to a specific
node kind. The target Run is authorized through the canonical Workspace
inspection door, and its Project is authoritative; a body project_id may
confirm that scope but cannot replace it.

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
from services.dag_run_inspection import visible_run_detail
from services.feedback_service import ALLOWED_THUMBS, record_thumb

from routes.audit import log_audit

# Agent Conductor is a single soft-org deployment unless middleware provides a
# resolved org. This value is used only after the canonical Run/Workspace door
# has authorized the feedback target; it cannot authorize an arbitrary project.
CONDUCTOR_ORG_ID = "default-org"

router = APIRouter(tags=["dag-feedback"])


class FeedbackBody(BaseModel):
    thumb: Literal["up", "down"]
    comment: str = Field(default="", max_length=2000)
    # Optional assertion of the Run's Project. It is rejected when it does
    # not match the authorized execution scope.
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


def _resolve_project_id(request: Request, body: FeedbackBody, run_project_id: str) -> str:
    """Use the authorized Run's Project, rejecting caller-supplied mismatches.

    A feedback body is not an authorization token. The run projection carries
    the Project resolved by canonical execution, so accepting a different body
    value would let a caller write feedback into another Outcome scope.
    """
    del request  # Kept in the helper signature for direct route-unit callers.
    project_id = str(run_project_id or "")
    if not project_id:
        raise HTTPException(status_code=403, detail="No project scope resolved for this run")
    if body.project_id and body.project_id != project_id:
        raise HTTPException(status_code=403, detail="Feedback project does not match the run")
    return project_id


def _resolve_org_id(request: Request) -> str:
    """Resolve the request org without converting an explicit blank to global."""
    marker = object()
    org_id = getattr(request.state, "org_id", marker)
    if org_id is marker:
        return CONDUCTOR_ORG_ID
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization scope resolved")
    return str(org_id)


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
    # Feedback is a write into the Outcome scope. Authorize the run through the
    # canonical Workspace membership door before resolving either scope axis.
    run = await visible_run_detail(user_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    project_id = _resolve_project_id(request, body, str(run.get("project_id") or ""))
    org_id = _resolve_org_id(request)

    try:
        result = await record_thumb(
            user_id=user_id,
            org_id=org_id,
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
