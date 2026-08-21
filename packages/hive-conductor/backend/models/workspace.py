"""Workspace — a live, per-user/shared instance of an adopted Persona.

Persona/Workspace system (replaces the hardcoded, globally-toggled PM Fleet
mode): a `PersonaTemplate` (maistro.personas, kind: workspace) declares a
persona's brand/voice/tools/scoped-UI. A Workspace is a specific instantiation
of one persona as a tab a user sees and switches between — deliberately thin,
carrying only what's per-instance: which persona, who owns/shares it, the
accepted capability checklist, and any per-workspace tool-binding overrides.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WorkspaceRole = Literal["owner", "editor", "viewer"]


class WorkspaceMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    role: WorkspaceRole = "owner"


class AgentToolBinding(BaseModel):
    """Phase E: per-workspace "sticky" override on top of the persona's
    declared spawns[].tools for one agent. Empty by default — a workspace
    with no bindings just inherits its persona's defaults."""

    model_config = ConfigDict(extra="ignore")

    agent_id: str
    tools: list[str] = Field(default_factory=list)
    prompt_fragment: str = ""


class Workspace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    persona_template_id: str
    name: str
    members: list[WorkspaceMember] = Field(default_factory=list)
    # Phase C: subset of the persona's declared tools/skills the user accepted.
    checklist: list[str] = Field(default_factory=list)
    # Phase E: per-workspace overrides; empty = pure persona defaults.
    tool_bindings: list[AgentToolBinding] = Field(default_factory=list)
    # Phase D: visual accent, one of services.themes.THEME_CATALOG's ids.
    theme_id: str = "default"
    # Phase D: overrides the persona's voice.tone for this workspace only;
    # None means "use the persona's declared tone as-is".
    voice_tone_override: str | None = None
    active: bool = True
    created_at: datetime
    updated_at: datetime
