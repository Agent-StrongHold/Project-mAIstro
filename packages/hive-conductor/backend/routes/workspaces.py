"""Workspace tabs over canonical Workspace identity and Hive presentation state.

Persona templates, checklist/theme choices, feedback, and tool bindings remain
Hive product behavior. Workspace identity, name, membership, and Root Project
ownership are delegated to ``maistro.workspaces`` through
``services.workspace_authority`` (#37).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from models.persona_feedback import PersonaFeedback, Thumb
from models.workspace import AgentToolBinding, Workspace, WorkspaceRole
from pydantic import BaseModel, ConfigDict, Field
from services.agent_materialization import materialize_workspace_agents, workspace_agents
from services.persona_authoring import (
    PersonaTemplateIdConflict,
    all_persona_templates,
    create_persona_template,
)
from services.persona_feedback import PersonaFeedbackSummary, summarize
from services.themes import THEME_CATALOG, ThemeOption, is_valid_theme_id
from services.workspace_authority import (
    create_workspace as create_canonical_workspace,
)
from services.workspace_authority import (
    delete_workspace as delete_canonical_workspace,
)
from services.workspace_authority import (
    list_views_for_user,
    member_role,
    remove_member,
    set_member,
    update_presentation,
    visible_view,
)

from maistro.personas.checklist import CapabilityItem, capability_checklist, default_checklist_ids
from maistro.personas.schema import InterviewQuestionSpec, SpawnSpec
from maistro.workspaces.model import WorkspaceAccessDenied

router = APIRouter(tags=["workspaces"])


def _now() -> datetime:
    return datetime.now(UTC)


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("id") or user.get("username") or "dev")


class PersonaChecklistResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    persona_template_id: str
    items: list[CapabilityItem]
    default_accepted: list[str]


class PersonaTemplateOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    display_name: str
    tagline: str


@router.get("/persona-templates", response_model=list[PersonaTemplateOption])
def list_persona_templates() -> list[PersonaTemplateOption]:
    """Every persona a workspace-creation picker can offer."""
    return [
        PersonaTemplateOption(
            id=template.id,
            display_name=template.brand.display_name or template.id,
            tagline=template.brand.tagline,
        )
        for template in all_persona_templates().values()
    ]


class PersonaAgentOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str
    role: str
    default_tools: list[str]
    default_skills: list[str]


@router.get("/persona-templates/{persona_id}/agents", response_model=list[PersonaAgentOption])
def get_persona_agents(persona_id: str) -> list[PersonaAgentOption]:
    """Every agent a persona declares for a tool-binding settings screen."""
    template = all_persona_templates().get(persona_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"unknown persona template: {persona_id}")
    return [
        PersonaAgentOption(
            agent_id=spawn.agent,
            role=spawn.role,
            default_tools=list(spawn.tools),
            default_skills=list(spawn.skills),
        )
        for spawn in template.spawns
    ]


class SpawnAgentSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent: str
    role: str = ""
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class InterviewQuestionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str
    agent: str = "intake"
    question: str


class CreatePersonaTemplateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    display_name: str
    tagline: str = ""
    archetype: str = ""
    audience: str = ""
    tone: str = ""
    ui_scope: list[str] = Field(default_factory=list)
    agents: list[SpawnAgentSpec] = Field(default_factory=list)
    interview: list[InterviewQuestionBody] = Field(default_factory=list)


@router.post("/persona-templates", response_model=PersonaTemplateOption, status_code=201)
def create_persona_template_route(body: CreatePersonaTemplateBody) -> PersonaTemplateOption:
    """PersonaWizard's finish step: author a brand-new persona in-app."""
    if not body.agents:
        raise HTTPException(status_code=422, detail="a persona needs at least one agent")
    try:
        template = create_persona_template(
            id=body.id,
            display_name=body.display_name,
            tagline=body.tagline,
            archetype=body.archetype,
            audience=body.audience,
            tone=body.tone,
            ui_scope=body.ui_scope,
            spawns=[
                SpawnSpec(agent=a.agent, role=a.role, tools=a.tools, skills=a.skills)
                for a in body.agents
            ],
            interview=[
                InterviewQuestionSpec(field=q.field, agent=q.agent, question=q.question)
                for q in body.interview
            ],
        )
    except PersonaTemplateIdConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PersonaTemplateOption(
        id=template.id,
        display_name=template.brand.display_name or template.id,
        tagline=template.brand.tagline,
    )


@router.get("/persona-templates/{persona_id}/checklist", response_model=PersonaChecklistResponse)
def get_persona_checklist(persona_id: str) -> PersonaChecklistResponse:
    """Return the capability checklist declared by one persona."""
    template = all_persona_templates().get(persona_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"unknown persona template: {persona_id}")
    return PersonaChecklistResponse(
        persona_template_id=persona_id,
        items=capability_checklist(template),
        default_accepted=default_checklist_ids(template),
    )


@router.get("/themes", response_model=list[ThemeOption])
def list_themes() -> list[ThemeOption]:
    return THEME_CATALOG


@router.get("/persona-templates/{persona_id}/feedback", response_model=PersonaFeedbackSummary)
def get_persona_feedback(persona_id: str) -> PersonaFeedbackSummary:
    """Aggregate feedback across Workspaces instantiating the same persona."""
    return summarize(persona_id, list(stores.persona_feedback.values()))


@router.get("", response_model=list[Workspace])
async def list_workspaces(request: Request) -> list[Workspace]:
    return await list_views_for_user(_user_id(request))


@router.get("/{workspace_id}", response_model=Workspace)
async def get_workspace(workspace_id: str, request: Request) -> Workspace:
    workspace = await visible_view(_user_id(request), workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace


class CreateWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    persona_template_id: str
    name: str
    checklist: list[str] | None = None
    theme_id: str = "default"
    voice_tone_override: str | None = None


@router.post("", response_model=Workspace, status_code=201)
async def create_workspace(body: CreateWorkspaceBody, request: Request) -> Workspace:
    if not is_valid_theme_id(body.theme_id):
        raise HTTPException(status_code=422, detail=f"unknown theme_id: {body.theme_id}")
    template = all_persona_templates().get(body.persona_template_id)
    checklist = body.checklist
    if checklist is None:
        checklist = default_checklist_ids(template) if template is not None else []
    workspace = await create_canonical_workspace(
        creator_user_id=_user_id(request),
        name=body.name,
        persona_template_id=body.persona_template_id,
        checklist=checklist,
        theme_id=body.theme_id,
        voice_tone_override=body.voice_tone_override,
    )
    if template is not None:
        materialize_workspace_agents(workspace.id, template)
    return workspace


class AddMemberBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    role: WorkspaceRole = "viewer"


@router.post("/{workspace_id}/members", response_model=Workspace)
async def add_workspace_member(
    workspace_id: str, body: AddMemberBody, request: Request
) -> Workspace:
    requester = _user_id(request)
    if await visible_view(requester, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    if await member_role(requester, workspace_id) != "owner":
        raise HTTPException(status_code=403, detail="only an owner can add workspace members")
    return await set_member(workspace_id, user_id=body.user_id, role=body.role)


@router.delete("/{workspace_id}/members/{user_id}", response_model=Workspace)
async def remove_workspace_member(workspace_id: str, user_id: str, request: Request) -> Workspace:
    requester = _user_id(request)
    if await visible_view(requester, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")

    target_role = await member_role(user_id, workspace_id)
    if target_role is None:
        raise HTTPException(status_code=404, detail="user is not a member of this workspace")

    is_self_removal = requester == user_id
    if await member_role(requester, workspace_id) != "owner" and not is_self_removal:
        raise HTTPException(status_code=403, detail="only an owner can remove other members")

    try:
        return await remove_member(workspace_id, user_id=user_id)
    except WorkspaceAccessDenied as exc:
        raise HTTPException(status_code=400, detail="cannot remove the workspace's last owner") from exc


class WorkspaceFeedbackBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    thumb: Thumb
    comment: str = Field(default="", max_length=2000)
    dag_run_id: str = ""
    node_id: str = ""


@router.post("/{workspace_id}/feedback", response_model=PersonaFeedback, status_code=201)
async def submit_workspace_feedback(
    workspace_id: str, body: WorkspaceFeedbackBody, request: Request
) -> PersonaFeedback:
    user_id = _user_id(request)
    workspace = await visible_view(user_id, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    feedback = PersonaFeedback(
        id=str(uuid4()),
        persona_template_id=workspace.persona_template_id,
        workspace_id=workspace_id,
        user_id=user_id,
        thumb=body.thumb,
        comment=body.comment,
        dag_run_id=body.dag_run_id,
        node_id=body.node_id,
        created_at=_now(),
    )
    stores.persona_feedback[feedback.id] = feedback
    return feedback


class UpdateWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active: bool | None = None


@router.patch("/{workspace_id}", response_model=Workspace)
async def update_workspace(
    workspace_id: str, body: UpdateWorkspaceBody, request: Request
) -> Workspace:
    requester = _user_id(request)
    if await visible_view(requester, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    if await member_role(requester, workspace_id) != "owner":
        raise HTTPException(status_code=403, detail="only an owner can update this workspace")
    return await update_presentation(workspace_id, active=body.active)


class UpdateToolBindingsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bindings: list[AgentToolBinding]


@router.put("/{workspace_id}/tool-bindings", response_model=Workspace)
async def update_tool_bindings(
    workspace_id: str, body: UpdateToolBindingsBody, request: Request
) -> Workspace:
    requester = _user_id(request)
    if await visible_view(requester, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    if await member_role(requester, workspace_id) != "owner":
        raise HTTPException(status_code=403, detail="only an owner can update tool bindings")
    return await update_presentation(workspace_id, tool_bindings=body.bindings)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, request: Request) -> None:
    requester = _user_id(request)
    if await visible_view(requester, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    if await member_role(requester, workspace_id) != "owner":
        raise HTTPException(status_code=403, detail="only an owner can delete this workspace")
    await delete_canonical_workspace(workspace_id)
    for agent in workspace_agents(workspace_id):
        stores.agents.pop(agent.id, None)
