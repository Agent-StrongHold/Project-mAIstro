"""Inbound A2A admission at the canonical Run boundary (#1194).

The endpoint intentionally does not create an independent A2A task record. The
returned task id is a receipt for the canonical Run, and the idempotency key is
claimed by the Run store before any work can be accepted.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from maistro.graph.definitions import Graph, Node
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.store import RunStore
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal

router = APIRouter(prefix="/a2a", tags=["a2a"])

_run_store: RunStore | None = None
_project_store: ProjectScopeStore | None = None
_workspace_id = ""


class A2ATaskCreate(BaseModel):
    """The small transport envelope accepted from a trusted guest peer."""

    agent_id: str = Field(min_length=1)
    messages: list[dict[str, str]] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1)


class A2ATaskCreated(BaseModel):
    task_id: str
    run_id: str
    status: str = "submitted"


def configure_a2a_admission(
    store: RunStore | None,
    project_store: ProjectScopeStore | None,
    *,
    workspace_id: str = "",
) -> None:
    """Install the same canonical stores used by the rest of the server."""
    global _run_store, _project_store, _workspace_id
    _run_store = store
    _project_store = project_store
    _workspace_id = workspace_id


def _stores() -> tuple[RunStore, ProjectScopeStore, str]:
    if _run_store is None or _project_store is None or not _workspace_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A2A admission is not configured",
        )
    return _run_store, _project_store, _workspace_id


@router.post("/tasks/create", status_code=status.HTTP_202_ACCEPTED)
async def create_a2a_task(
    request: A2ATaskCreate,
    auth: RequireAuth,
) -> A2ATaskCreated:
    """Durably admit one idempotent remote delegation.

    Authentication identifies the peer principal, while this service's
    configured Workspace selects its own destination scope. A caller cannot
    smuggle a tenant selector through the A2A body.
    """
    store, projects, workspace_id = _stores()
    root = await projects.root_for_workspace(workspace_id)
    text = "\n".join(str(message.get("content", "")) for message in request.messages)
    graph = Graph(
        workspace_id=workspace_id,
        project_id=root.project_id,
        name=f"a2a:{request.agent_id}",
        nodes=[
            Node(
                node_type="agent.remote_work",
                name=request.agent_id,
                inputs={"task": text, "agent_id": request.agent_id},
            )
        ],
    )
    principal = auth if isinstance(auth, AuthenticatedPrincipal) else None
    claim = await store.claim_run_by_effect(
        graph,
        effect_key=request.idempotency_key,
        actor_principal_id=principal.user_id if principal is not None else None,
        provenance={
            "admission_source": "a2a_delegation",
            "a2a_task_id": request.idempotency_key,
            "a2a_agent_id": request.agent_id,
            "a2a_messages": request.messages,
        },
    )
    return A2ATaskCreated(task_id=claim.run.run_id, run_id=claim.run.run_id)
