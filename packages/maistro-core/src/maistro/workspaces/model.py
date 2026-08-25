from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceRole(StrEnum):
    MEMBER = "member"
    CONTRIBUTOR = "contributor"
    OWNER = "owner"


class Workspace(BaseModel):
    """A durable MAIstro product environment.

    Workspace identity and Workspace access are intentionally separate.
    Ownership is represented by WorkspaceMembership, not by a user field on the
    Workspace record itself.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    description: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("workspace_id", "name")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class WorkspaceMembership(BaseModel):
    """One user's access relationship to one Workspace."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    user_id: str
    role: WorkspaceRole = WorkspaceRole.MEMBER
    added_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("workspace_id", "user_id")
    @classmethod
    def _require_non_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @property
    def can_use(self) -> bool:
        return True

    @property
    def can_contribute(self) -> bool:
        return self.role in {WorkspaceRole.CONTRIBUTOR, WorkspaceRole.OWNER}

    @property
    def can_administer(self) -> bool:
        return self.role is WorkspaceRole.OWNER


# Backward-compatible alias: WorkspaceMembership is the canonical identity;
# WorkspaceMember remains only for pre-convergence import compatibility.
WorkspaceMember = WorkspaceMembership


class WorkspaceNotFound(KeyError):
    pass


class WorkspaceAccessDenied(PermissionError):
    pass


class WorkspaceOwnershipError(ValueError):
    pass


__all__ = [
    "Workspace",
    "WorkspaceAccessDenied",
    "WorkspaceMember",
    "WorkspaceMembership",
    "WorkspaceNotFound",
    "WorkspaceOwnershipError",
    "WorkspaceRole",
]
