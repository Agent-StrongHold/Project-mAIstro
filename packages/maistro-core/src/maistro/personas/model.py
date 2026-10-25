"""Live Persona domain model.

Persona is the Workspace's taste, style, purpose, and behavioral configuration.
It is not an actor, ownership boundary, execution lifecycle, or authorization
layer. Security authority is resolved from Principal/Workspace/Project scopes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PersonaSurface(StrEnum):
    """Well-known product surfaces a Persona may configure/expose."""

    UI = "ui"
    API = "api"
    BUILDERS_CLI = "builders_cli"
    BUILDERS_RSI = "builders_rsi"


class Persona(BaseModel):
    """The single live taste/style/purpose context for a Workspace."""

    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    name: str
    purpose: str = ""
    description: str = ""
    theme: str | None = None

    taste: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    style_guidance: str = ""

    surfaces: set[str] = Field(default_factory=set)

    node_template_ids: list[str] = Field(default_factory=list)
    graph_template_ids: list[str] = Field(default_factory=list)

    preferred_capability_ids: list[str] = Field(default_factory=list)
    preferred_binding_ids: list[str] = Field(default_factory=list)
    default_model_id: str | None = None
    default_provider_id: str | None = None

    defaults: dict[str, Any] = Field(default_factory=dict)
    behavior_defaults: dict[str, Any] = Field(default_factory=dict)

    source_template_id: str | None = None
    source_template_version: str | None = None
    extension_metadata: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("id", "workspace_id", "name")
    @classmethod
    def _require_non_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("surfaces")
    @classmethod
    def _require_non_blank_surfaces(cls, values: set[str]) -> set[str]:
        if any(not value.strip() for value in values):
            raise ValueError("surface names must be non-empty strings")
        return values

    def exposes_surface(self, surface: str | PersonaSurface) -> bool:
        """Return whether this Persona configures a named product surface."""

        return str(surface) in self.surfaces


__all__ = ["Persona", "PersonaSurface"]
