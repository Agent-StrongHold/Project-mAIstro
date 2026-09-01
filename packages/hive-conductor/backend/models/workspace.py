"""Hive presentation models over the canonical MAIstro Workspace authority.

`maistro.workspaces` owns Workspace identity, name, and membership. Hive keeps
only persona/UI choices that are specific to this product, keyed by the
canonical ``workspace_id``. `Workspace` remains the HTTP response shape so the
existing frontend does not have to learn where each field is persisted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WorkspaceRole = Literal["owner", "editor", "viewer"]


class WorkspaceMember(BaseModel):
    """HTTP projection of a canonical WorkspaceMembership."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    role: WorkspaceRole = "owner"


class AgentToolBinding(BaseModel):
    """Per-workspace Hive override on top of the persona's declared tools."""

    model_config = ConfigDict(extra="ignore")

    agent_id: str
    tools: list[str] = Field(default_factory=list)
    prompt_fragment: str = ""


class WorkspacePresentation(BaseModel):
    """Hive-owned fields attached to one canonical Workspace identity.

    The key is a foreign identity reference, not another Workspace ID owner.
    Name, membership, and creation time are deliberately absent.
    """

    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    persona_template_id: str
    checklist: list[str] = Field(default_factory=list)
    tool_bindings: list[AgentToolBinding] = Field(default_factory=list)
    theme_id: str = "default"
    voice_tone_override: str | None = None
    active: bool = True
    updated_at: datetime


class Workspace(BaseModel):
    """Compatibility response composed from canonical + Hive-owned records."""

    model_config = ConfigDict(extra="ignore")

    id: str
    persona_template_id: str
    name: str
    members: list[WorkspaceMember] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    tool_bindings: list[AgentToolBinding] = Field(default_factory=list)
    theme_id: str = "default"
    voice_tone_override: str | None = None
    active: bool = True
    created_at: datetime
    updated_at: datetime
