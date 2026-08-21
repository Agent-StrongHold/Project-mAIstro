"""Workspace tabs — Persona/Workspace system (replaces the hardcoded PM Fleet mode).

Phase A: manual create/list/get. Phase C adds the persona-template checklist
endpoint (accept/modify tools/skills derived from the chosen persona's own
declared spawns). Phase D adds the theme catalog + per-workspace tone
override. Phase G adds member management (invite/remove, owner/editor/viewer
roles). Phase I adds thumbs +/- + comment feedback, persisted per-persona so
it aggregates across every workspace instantiating that persona. PersonaWizard
slice adds a writable persona-template store (services/persona_authoring.py)
and a route to set a workspace's sticky per-agent tool bindings
(services/tool_binding.py, Phase E — this is the first route that lets
anyone actually write them).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from models.persona_feedback import PersonaFeedback, Thumb
from models.workspace import AgentToolBinding, Workspace, WorkspaceMember, WorkspaceRole
from pydantic import BaseModel, ConfigDict, Field
from services.agent_materialization import materialize_workspace_agents, workspace_agents
from services.persona_authoring import (
    PersonaTemplateIdConflict,
    all_persona_templates,
    create_persona_template,
)
from services.persona_feedback import PersonaFeedbackSummary, summarize
from services.themes import THEME_CATALOG, ThemeOption, is_valid_theme_id

from maistro.personas.checklist import CapabilityItem, capability_checklist, default_checklist_ids
from maistro.personas.schema import InterviewQuestionSpec, SpawnSpec

router = APIRouter(tags=["workspaces"])


def _now() -> datetime:
    return datetime.now(UTC)


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("id") or user.get("username") or "dev")


def _visible_to(user_id: str, workspace: Workspace) -> bool:
    return any(m.user_id == user_id for m in workspace.members)


def _member_role(workspace: Workspace, user_id: str) -> WorkspaceRole | None:
    for m in workspace.members:
        if m.user_id == user_id:
            return m.role
    return None


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
    """Every persona a workspace-creation picker can offer -- "unlimited
    personas" means unlimited YAML files (built-in or wizard-authored), not a
    hardcoded catalog here."""
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
    """Every agent a persona declares, for a tool-binding settings screen to
    offer -- derived from the template's own `spawns`, same "no separate
    hardcoded catalog" posture as the checklist endpoint."""
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
    # Optional custom onboarding-interview script for this persona -- empty
    # means "no custom script", same as a hand-authored persona that never
    # declared `interview:` in its YAML (falls back to the generic one).
    interview: list[InterviewQuestionBody] = Field(default_factory=list)


@router.post("/persona-templates", response_model=PersonaTemplateOption, status_code=201)
def create_persona_template_route(body: CreatePersonaTemplateBody) -> PersonaTemplateOption:
    """PersonaWizard's finish step: author a brand-new persona in-app instead
    of hand-editing a YAML file. Persisted alongside the built-ins (see
    services/persona_authoring.py) so it's immediately usable as a
    workspace-creation choice."""
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
    """The checklist a workspace-creation wizard shows: every tool/skill the
    chosen persona declares, derived from its own `spawns` -- not a separate
    hardcoded catalog. `default_accepted` pre-checks everything; the wizard
    lets the user uncheck what they don't want."""
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
    """Aggregated thumbs +/- across every workspace instantiating this
    persona -- not scoped to one workspace, since the whole point is that
    feedback steers the persona itself, wherever it's adopted."""
    return summarize(persona_id, list(stores.persona_feedback.values()))


@router.get("", response_model=list[Workspace])
def list_workspaces(request: Request) -> list[Workspace]:
    user_id = _user_id(request)
    return [w for w in stores.workspaces.values() if _visible_to(user_id, w)]


@router.get("/{workspace_id}", response_model=Workspace)
def get_workspace(workspace_id: str, request: Request) -> Workspace:
    workspace = stores.workspaces.get(workspace_id)
    if workspace is None or not _visible_to(_user_id(request), workspace):
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace


class CreateWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    persona_template_id: str
    name: str
    # Accept/modify result from GET .../checklist. Omitted or null means
    # "accept everything the persona declares" (if it resolves); an explicit
    # list -- including [] -- is honored exactly, so a user can deliberately
    # start a workspace with zero enabled capabilities.
    checklist: list[str] | None = None
    # Phase D: visual accent, one of GET /themes' ids. Invalid ids 422 rather
    # than silently falling back, so a wizard can't produce an unrenderable tab.
    theme_id: str = "default"
    voice_tone_override: str | None = None


@router.post("", response_model=Workspace, status_code=201)
def create_workspace(body: CreateWorkspaceBody, request: Request) -> Workspace:
    if not is_valid_theme_id(body.theme_id):
        raise HTTPException(status_code=422, detail=f"unknown theme_id: {body.theme_id}")
    user_id = _user_id(request)
    workspace_id = str(uuid4())
    t = _now()
    template = all_persona_templates().get(body.persona_template_id)
    checklist = body.checklist
    if checklist is None:
        checklist = default_checklist_ids(template) if template is not None else []
    workspace = Workspace(
        id=workspace_id,
        persona_template_id=body.persona_template_id,
        name=body.name,
        members=[WorkspaceMember(user_id=user_id, role="owner")],
        checklist=checklist,
        theme_id=body.theme_id,
        voice_tone_override=body.voice_tone_override,
        created_at=t,
        updated_at=t,
    )
    stores.workspaces[workspace_id] = workspace
    # Materialize the persona's own declared agents as real, workspace-scoped
    # Agent records (services/agent_materialization.py) -- every persona is
    # treated identically here, not just pm_fleet.
    if template is not None:
        materialize_workspace_agents(workspace_id, template)
    return workspace


class AddMemberBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    role: WorkspaceRole = "viewer"


@router.post("/{workspace_id}/members", response_model=Workspace)
def add_workspace_member(workspace_id: str, body: AddMemberBody, request: Request) -> Workspace:
    """Invite/add a member. Only an existing owner may do this; re-adding an
    already-present user_id updates their role rather than erroring."""
    workspace = stores.workspaces.get(workspace_id)
    requester = _user_id(request)
    if workspace is None or not _visible_to(requester, workspace):
        raise HTTPException(status_code=404, detail="workspace not found")
    if _member_role(workspace, requester) != "owner":
        raise HTTPException(status_code=403, detail="only an owner can add workspace members")
    members = [m for m in workspace.members if m.user_id != body.user_id]
    members.append(WorkspaceMember(user_id=body.user_id, role=body.role))
    workspace = workspace.model_copy(update={"members": members, "updated_at": _now()})
    stores.workspaces[workspace_id] = workspace
    return workspace


@router.delete("/{workspace_id}/members/{user_id}", response_model=Workspace)
def remove_workspace_member(workspace_id: str, user_id: str, request: Request) -> Workspace:
    """Remove a member. An owner may remove anyone; anyone may remove
    themselves. The workspace's last owner cannot be removed by anyone --
    including themselves -- so a shared workspace never goes ownerless."""
    workspace = stores.workspaces.get(workspace_id)
    requester = _user_id(request)
    if workspace is None or not _visible_to(requester, workspace):
        raise HTTPException(status_code=404, detail="workspace not found")

    target_role = _member_role(workspace, user_id)
    if target_role is None:
        raise HTTPException(status_code=404, detail="user is not a member of this workspace")

    is_self_removal = requester == user_id
    if _member_role(workspace, requester) != "owner" and not is_self_removal:
        raise HTTPException(status_code=403, detail="only an owner can remove other members")

    remaining = [m for m in workspace.members if m.user_id != user_id]
    if target_role == "owner" and not any(m.role == "owner" for m in remaining):
        raise HTTPException(status_code=400, detail="cannot remove the workspace's last owner")

    workspace = workspace.model_copy(update={"members": remaining, "updated_at": _now()})
    stores.workspaces[workspace_id] = workspace
    return workspace


class WorkspaceFeedbackBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    thumb: Thumb
    comment: str = Field(default="", max_length=2000)
    # Optional pointers back to a specific DAG run, if this feedback is about
    # one -- purely for traceability alongside services/feedback_service.py's
    # separate, DAG-scoped signal. Neither is required.
    dag_run_id: str = ""
    node_id: str = ""


@router.post("/{workspace_id}/feedback", response_model=PersonaFeedback, status_code=201)
def submit_workspace_feedback(
    workspace_id: str, body: WorkspaceFeedbackBody, request: Request
) -> PersonaFeedback:
    """Any member (including a viewer) may give feedback -- it's persisted
    against the workspace's persona, not the workspace itself, so it
    aggregates across every workspace instantiating that persona."""
    workspace = stores.workspaces.get(workspace_id)
    user_id = _user_id(request)
    if workspace is None or not _visible_to(user_id, workspace):
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

    # Archive/unarchive. Omitted means "no change" -- distinct from an
    # explicit value, so this endpoint can later grow other patchable
    # fields without every caller having to resend `active`.
    active: bool | None = None


@router.patch("/{workspace_id}", response_model=Workspace)
def update_workspace(workspace_id: str, body: UpdateWorkspaceBody, request: Request) -> Workspace:
    """Archive/unarchive a workspace (soft, reversible) -- only an owner may
    change workspace-level settings."""
    workspace = stores.workspaces.get(workspace_id)
    requester = _user_id(request)
    if workspace is None or not _visible_to(requester, workspace):
        raise HTTPException(status_code=404, detail="workspace not found")
    if _member_role(workspace, requester) != "owner":
        raise HTTPException(status_code=403, detail="only an owner can update this workspace")

    updates: dict[str, object] = {"updated_at": _now()}
    if body.active is not None:
        updates["active"] = body.active
    workspace = workspace.model_copy(update=updates)
    stores.workspaces[workspace_id] = workspace
    return workspace


class UpdateToolBindingsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bindings: list[AgentToolBinding]


@router.put("/{workspace_id}/tool-bindings", response_model=Workspace)
def update_tool_bindings(
    workspace_id: str, body: UpdateToolBindingsBody, request: Request
) -> Workspace:
    """Replace a workspace's sticky per-agent tool/prompt overrides wholesale
    -- same owner-only posture as every other workspace-settings mutation.
    services/tool_binding.py's resolve_agent_tools()/
    resolve_agent_prompt_fragment() (Phase E) already consume
    `Workspace.tool_bindings`; this is the first route that lets anyone
    actually set them, rather than editing them by hand in the store."""
    workspace = stores.workspaces.get(workspace_id)
    requester = _user_id(request)
    if workspace is None or not _visible_to(requester, workspace):
        raise HTTPException(status_code=404, detail="workspace not found")
    if _member_role(workspace, requester) != "owner":
        raise HTTPException(status_code=403, detail="only an owner can update tool bindings")
    workspace = workspace.model_copy(update={"tool_bindings": body.bindings, "updated_at": _now()})
    stores.workspaces[workspace_id] = workspace
    return workspace


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, request: Request) -> None:
    """Permanently remove a workspace -- only an owner may do this. Unlike
    archiving (PATCH .../active=false, reversible), this is not."""
    workspace = stores.workspaces.get(workspace_id)
    requester = _user_id(request)
    if workspace is None or not _visible_to(requester, workspace):
        raise HTTPException(status_code=404, detail="workspace not found")
    if _member_role(workspace, requester) != "owner":
        raise HTTPException(status_code=403, detail="only an owner can delete this workspace")
    for agent in workspace_agents(workspace_id):
        stores.agents.pop(agent.id, None)
    stores.workspaces.pop(workspace_id, None)
