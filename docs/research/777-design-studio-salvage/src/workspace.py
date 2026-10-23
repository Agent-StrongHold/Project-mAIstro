"""Workspace context management for Design Studio.

Workspace memory supplies scoped context. Design Studio consumes Workspace context
through #776 without cross-Workspace bleed.

This does not duplicate Workspace Agent or Goal semantics; it's a Design Studio
projection that can coexist with the canonical ownership structure.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


class WorkspaceContext:
    """Manage Workspace context for Design Studio.

    This consumes Workspace context without cross-Workspace bleed, as specified in #776.
    """

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self._context: dict[str, Any] = {}
        self._initialized = False

    async def load(self) -> None:
        """Load Workspace context from the #776 Ladybug working graph."""
        logger.info("loading_workspace_context", workspace_id=self.workspace_id)

        # Load relevant Workspace context
        # This would consume the #776 Workspace Ladybug working graph API
        # For now, create a placeholder context

        self._context = {
            "workspace_id": self.workspace_id,
            "persona_template": "program_manager",  # Default persona
            "design_system": "default",  # Default design system
            "workspace_memory": {},
            "available_tools": ["canvas", "builders", "deck_builder", "media_provider"],
        }

        self._initialized = True
        logger.info("workspace_context_loaded", context_keys=list(self._context.keys()))

    async def get_relevant_context(self) -> dict[str, Any]:
        """Get relevant Workspace context without cross-Workspace bleed.

        Returns only the context needed for Design Studio operations.
        """
        if not self._initialized:
            await self.load()

        # Filter to only relevant context for Design Studio
        relevant_context = {
            "workspace_id": self._context["workspace_id"],
            "persona_template": self._context["persona_template"],
            "design_system": self._context["design_system"],
            "workspace_memory": self._context["workspace_memory"],
        }

        logger.info("workspace_context_retrieved", relevant_keys=list(relevant_context.keys()))
        return relevant_context

    async def update_memory(self, key: str, value: Any) -> None:
        """Update Workspace memory with new context."""
        logger.info("updating_workspace_memory", workspace_id=self.workspace_id, key=key)

        if "workspace_memory" not in self._context:
            self._context["workspace_memory"] = {}

        self._context["workspace_memory"][key] = value
        logger.info("workspace_memory_updated", key=key)

    async def get_scoped_context(self, scope: str | None = None) -> dict[str, Any]:
        """Get Workspace context scoped to a specific area.

        This prevents cross-Workspace bleed by ensuring each Design Studio
        operation only sees its relevant context.
        """
        base_context = await self.get_relevant_context()

        if not scope:
            return base_context

        # Filter context based on scope
        scoped_context = {}
        for key, value in base_context.items():
            if key in ["workspace_id", "persona_template", "design_system"]:
                scoped_context[key] = value
            elif key == "workspace_memory" and isinstance(value, dict):
                # Only include memory relevant to this scope
                scoped_context[key] = {k: v for k, v in value.items() if scope in k or k == scope}
            else:
                scoped_context[key] = value

        logger.info("scoped_workspace_context", scope=scope, keys=list(scoped_context.keys()))
        return scoped_context

    async def validate_scope_access(self, other_workspace_id: str) -> bool:
        """Validate that accessing another Workspace's context is allowed.

        This enforces the no-cross-Workspace-bleed invariant.
        """
        # Design Studio should only access its own workspace
        is_valid = self.workspace_id == other_workspace_id

        if not is_valid:
            logger.warning(
                "workspace_access_validation_failed",
                requesting_workspace=self.workspace_id,
                target_workspace=other_workspace_id,
            )

        return is_valid
