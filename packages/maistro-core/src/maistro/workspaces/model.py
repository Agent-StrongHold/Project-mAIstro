from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _naive_as_utc(value: datetime) -> datetime:
    """A bare wall-clock value here means UTC, not the reading process's zone.

    `astimezone()` on a naive datetime asks the platform to guess the zone it
    was written in, so the same stored row would decode to a different instant
    depending on which host reads it (#1149). Matches the normalization
    `maistro.scheduling.model.Schedule` already applies to its own timestamps.

    Awareness is determined by `utcoffset()`, not merely by `tzinfo is not
    None`: a `tzinfo` object that itself returns `None` from `utcoffset()` is
    naive per Python's own definition and must still be normalized to UTC.
    """

    return value if value.utcoffset() is not None else value.replace(tzinfo=UTC)


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

    @model_validator(mode="after")
    def _normalize_timestamps(self) -> Workspace:
        object.__setattr__(self, "created_at", _naive_as_utc(self.created_at))
        object.__setattr__(self, "updated_at", _naive_as_utc(self.updated_at))
        return self


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

    @model_validator(mode="after")
    def _normalize_added_at(self) -> WorkspaceMembership:
        object.__setattr__(self, "added_at", _naive_as_utc(self.added_at))
        return self

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


class WorkspaceRetainsHistory(Exception):
    """Deletion was refused because durable Run history references the tree.

    `canonical_runs.project_id` is `ON DELETE RESTRICT` (migration 012): a
    Project a Run was filed under cannot be purged, so neither can the
    Workspace above it. The store restores the Workspace to ``active`` before
    raising, so the refusal leaves it visible rather than hidden ``deleting``.
    """

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        super().__init__(
            f"Workspace {workspace_id!r} owns canonical Run history that must be retained; "
            "it cannot be deleted"
        )


__all__ = [
    "Workspace",
    "WorkspaceAccessDenied",
    "WorkspaceMember",
    "WorkspaceMembership",
    "WorkspaceNotFound",
    "WorkspaceOwnershipError",
    "WorkspaceRetainsHistory",
    "WorkspaceRole",
]
