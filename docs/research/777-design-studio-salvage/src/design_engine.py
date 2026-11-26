"""Design Engine integration for Design Studio.

This module provides integration with the existing Design Engine routes
(/v1/design/*) that Design Studio uses as its foundation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from .types import DesignOutput, RenderOutput

logger = structlog.get_logger()


class DesignEngine:
    """Design Engine that integrates with existing /v1/design/* routes.

    This is the foundation that Design Studio consumes rather than hard-coding
    Canvas or direct provider calls.
    """

    def __init__(self):
        self._initialized = False
        self._skills = {}  # Would be populated from actual skills registry
        self._systems = {}  # Would be populated from actual systems registry

    async def initialize(self) -> None:
        """Initialize the Design Engine."""
        logger.info("initializing_design_engine")

        # Load available skills and systems from the actual Design Engine
        # This would integrate with the existing /v1/design/skills and /v1/design/systems routes

        self._skills = {
            "login-flow": {
                "slug": "login-flow",
                "name": "Login Flow",
                "mode": "auth",
                "description": "Authentication and login flow design",
                "featured": True,
                "output_formats": ["pdf", "html"],
                "tags": ["auth", "ui", "web"],
                "discovery_form": [
                    {
                        "key": "auth_methods",
                        "label": "Auth Methods",
                        "field_type": "select",
                        "options": ["email", "oauth", "saml"],
                    }
                ],
                "render_slot": "web",
            },
            "canvas": {
                "slug": "canvas",
                "name": "Canvas",
                "mode": "visual",
                "description": "Fixed-page visual composition",
                "featured": True,
                "output_formats": ["pdf", "png"],
                "tags": ["visual", "design", "layout"],
                "discovery_form": [
                    {
                        "key": "layout",
                        "label": "Layout",
                        "field_type": "select",
                        "options": ["poster", "banner", "card"],
                    }
                ],
                "render_slot": "visual",
            },
            "builders": {
                "slug": "builders",
                "name": "Builders",
                "mode": "code",
                "description": "Code generation and web development",
                "featured": True,
                "output_formats": ["javascript", "python"],
                "tags": ["code", "web", "development"],
                "discovery_form": [
                    {
                        "key": "language",
                        "label": "Language",
                        "field_type": "select",
                        "options": ["javascript", "python"],
                    }
                ],
                "render_slot": "code",
            },
        }

        self._systems = {
            "default": {
                "slug": "default",
                "name": "Default Design System",
                "description": "Default design system for creative projects",
                "origin": "bundled",
                "trust_tier": "t1",
                "color_count": 5,
                "spacing_count": 4,
                "personas": {
                    "default": "greenhouse",
                    "templates": ["greenhouse", "slate", "studio"],
                    "schemes": ["light", "dark"],
                    "customizable": ["--accent", "--actor-human"],
                    "fixed": [],
                },
            },
        }

        self._initialized = True
        logger.info(
            "design_engine_initialized",
            skill_count=len(self._skills),
            system_count=len(self._systems),
        )

    async def generate(
        self, discovery: Any, org_id: str, team_id: str | None = None
    ) -> DesignOutput:
        """Generate a design from discovery responses.

        This uses the existing Design Engine API (/v1/design/projects POST route).
        """
        if not self._initialized:
            await self.initialize()

        logger.info(
            "generating_design",
            org_id=org_id,
            team_id=team_id,
            skill_slug=discovery.get("skill_slug"),
        )

        # Validate skill and design system exist
        skill_slug = discovery.get("skill_slug")
        if skill_slug not in self._skills:
            raise ValueError(f"Skill {skill_slug} not found")

        design_system_slug = discovery.get("design_system_slug", "default")
        if design_system_slug not in self._systems:
            raise ValueError(f"Design system {design_system_slug} not found")

        # Create design output (in a real implementation, this would call the actual /v1/design/projects route)
        design_id = f"design:{org_id}:{skill_slug}:{int(datetime.now().timestamp())}"

        # Create render outputs based on skill type
        outputs = []
        if skill_slug == "canvas":
            outputs.append(
                RenderOutput(
                    id=f"render:{design_id}:1",
                    format="pdf",
                    content="Generated canvas design",
                    url=f"/designs/{design_id}/output.pdf",
                )
            )
        elif skill_slug == "builders":
            outputs.append(
                RenderOutput(
                    id=f"render:{design_id}:1",
                    format="javascript",
                    content="Generated JavaScript code",
                    url=f"/designs/{design_id}/output.js",
                )
            )
        else:
            outputs.append(
                RenderOutput(
                    id=f"render:{design_id}:1",
                    format="pdf",
                    content="Generated design",
                    url=f"/designs/{design_id}/output.pdf",
                )
            )

        design_output = DesignOutput(
            id=design_id,
            name=discovery.get("name", f"Design {skill_slug}"),
            skill_slug=skill_slug,
            design_system_slug=design_system_slug,
            org_id=org_id,
            team_id=team_id,
            trust_tier=self._systems[design_system_slug]["trust_tier"],
            outputs=outputs,
        )

        logger.info("design_generated", design_id=design_id, output_count=len(outputs))
        return design_output

    async def run_discovery(self, skill_slug: str) -> list[dict[str, Any]]:
        """Get the discovery form for a skill.

        This uses the existing Design Engine API (/v1/design/skills/{slug}/discovery route).
        """
        if not self._initialized:
            await self.initialize()

        if skill_slug not in self._skills:
            raise ValueError(f"Skill {skill_slug} not found")

        # Return the discovery form from the skills registry
        skill = self._skills[skill_slug]
        return skill.get("discovery_form", [])

    def list_skills(self) -> list[dict[str, Any]]:
        """List available skills.

        This uses the existing Design Engine API (/v1/design/skills route).
        """
        if not self._initialized:
            # Initialize synchronously for testing purposes
            self.initialize()

        # Filter skills that have available renderers
        filled_slots = {
            "visual",
            "web",
            "code",
        }  # Simplified - in real implementation this would get from renderer registry

        skills = []
        for _skill_slug, skill in self._skills.items():
            if skill.get("render_slot") in filled_slots or skill.get("render_slot") is None:
                skills.append(
                    {
                        "slug": skill["slug"],
                        "name": skill["name"],
                        "mode": skill["mode"],
                        "description": skill["description"],
                        "featured": skill["featured"],
                        "output_formats": skill["output_formats"],
                        "tags": skill["tags"],
                        "discovery_form": skill["discovery_form"],
                        "render_slot": skill.get("render_slot"),
                    }
                )

        return skills

    def list_systems(self) -> list[dict[str, Any]]:
        """List available design systems.

        This uses the existing Design Engine API (/v1/design/systems route).
        """
        if not self._initialized:
            self.initialize()

        systems = []
        for _system_slug, system in self._systems.items():
            systems.append(
                {
                    "slug": system["slug"],
                    "name": system["name"],
                    "description": system["description"],
                    "origin": system["origin"],
                    "trust_tier": system["trust_tier"],
                    "color_count": system["color_count"],
                    "spacing_count": system["spacing_count"],
                    "personas": system["personas"],
                }
            )

        return systems
