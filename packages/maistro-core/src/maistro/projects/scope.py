"""Canonical Project scope domain.

A Project is a nested organization, configuration, authorization, and resource
scope inside a Workspace. It is not an execution lifecycle and it is not a
Workspace alias.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _id() -> str:
    return uuid.uuid4().hex


class Project(BaseModel):
    """One durable scope in a Workspace Project tree."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(default_factory=_id)
    workspace_id: str
    name: str
    parent_project_id: str | None
    is_root: bool = False
    defaults: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("project_id", "workspace_id", "name")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _root_shape(self) -> Project:
        if self.is_root and self.parent_project_id is not None:
            raise ValueError("Root Project cannot have a parent")
        if not self.is_root and self.parent_project_id is None:
            raise ValueError("non-root Project requires parent_project_id")
        return self


class ProjectMembership(BaseModel):
    """One principal's authority additions/restrictions in one Project scope."""

    model_config = ConfigDict(extra="forbid")

    membership_id: str = Field(default_factory=_id)
    workspace_id: str
    project_id: str
    principal_id: str
    role: str | None = None
    grants: set[str] = Field(default_factory=set)
    denies: set[str] = Field(default_factory=set)
    delegable_grants: set[str] = Field(default_factory=set)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("membership_id", "workspace_id", "project_id", "principal_id")
    @classmethod
    def _non_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("grants", "denies", "delegable_grants")
    @classmethod
    def _non_blank_actions(cls, values: set[str]) -> set[str]:
        if any(not value.strip() for value in values):
            raise ValueError("permission actions must be non-empty strings")
        return values

    @model_validator(mode="after")
    def _delegation_requires_grant(self) -> ProjectMembership:
        if not self.delegable_grants.issubset(self.grants):
            raise ValueError("delegable_grants must be a subset of grants")
        return self


class ProjectScopedResource(BaseModel):
    """Reference to a resource whose visibility flows down a Project subtree."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str
    workspace_id: str
    project_id: str
    resource_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("resource_id", "workspace_id", "project_id", "resource_type")
    @classmethod
    def _non_blank_resource(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class ProjectNotFound(KeyError):
    """Raised when a canonical Project does not exist."""


class ProjectIntegrityError(ValueError):
    """Raised when a Project tree or Workspace invariant would be violated."""


class ProjectNotEmpty(ProjectIntegrityError):
    """Raised when deletion is requested for a non-empty Project."""


class ProjectScopeDenied(PermissionError):
    """Raised when a scoped operation is not authorized or visible."""


__all__ = [
    "Project",
    "ProjectIntegrityError",
    "ProjectMembership",
    "ProjectNotEmpty",
    "ProjectNotFound",
    "ProjectScopeDenied",
    "ProjectScopedResource",
]
