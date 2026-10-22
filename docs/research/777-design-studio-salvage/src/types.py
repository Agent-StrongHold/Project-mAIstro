"""Types used by Design Studio.

This module defines the common data types and structures used by Design Studio
components.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class DesignSystem:
    """Visual/brand constraints and rules."""

    id: str
    name: str
    description: str
    colors: list[str]
    spacing: list[str]
    fonts: list[str]
    trust_tier: str  # "t1", "t2", "t3"
    personas: dict[str, str] | None = None
    schemes: dict[str, dict[str, str]] | None = None
    customizable: list[str] | None = None
    fixed: list[str] | None = None


@dataclass
class Persona:
    """Persistent flavor/taste/purpose for Design Studio."""

    id: str
    name: str
    description: str
    template_id: str  # Reference to persona template
    voice: str = "default"
    style_guidelines: dict[str, Any] | None = None


@dataclass
class DiscoveryForm:
    """Skill discovery form for Design Studio skills."""

    skill_slug: str
    fields: list[dict[str, Any]]
    metadata: dict[str, Any] | None = None


@dataclass
class RenderOutput:
    """Output from a design rendering operation."""

    id: str
    format: str
    content: str
    url: str | None = None
    trust_tier: str = "t1"
    metadata: dict[str, Any] | None = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class DesignOutput:
    """Output from a design generation operation."""

    id: str
    name: str
    skill_slug: str
    design_system_slug: str
    org_id: str
    team_id: str | None = None
    trust_tier: str = "t1"
    outputs: list[RenderOutput]
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "id": self.id,
            "name": self.name,
            "skill_slug": self.skill_slug,
            "design_system_slug": self.design_system_slug,
            "org_id": self.org_id,
            "team_id": self.team_id,
            "trust_tier": self.trust_tier,
            "outputs": [o.__dict__ for o in self.outputs],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
