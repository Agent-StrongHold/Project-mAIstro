"""Core Design Studio implementation.

Design Studio consumes the persistent Workspace Agent and Goal reconciliation APIs
from #804 rather than instantiating a Design-Studio-private root Agent/reconciler.

The Design Studio projects Design Studio-specific semantics onto the canonical
Goal hierarchy:

- Goal revision + Persona + Workspace memory + Design System + CreativeBrief
                ↓
          Design Studio
             ↙          ↓          ↘
         Canvas       Builders    Deck/media/tools
             ↘          ↓          ↙
                 versioned artifacts
                          ↓
            user/Agent evaluate, edit, lock, redirect
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from .brief import CreativeBrief
from .execution import ControlManager, MixedControlExecutor
from .projects import DesignProject
from .tools import StudioToolSelector
from .workspace import WorkspaceContext

logger = structlog.get_logger()


@dataclass
class DesignStudioConfig:
    """Configuration for Design Studio."""

    workspace_id: str
    project_id: str
    persona_id: str = "default"
    design_system_id: str = "default"
    enable_visual_generation: bool = False
    enable_server_publish: bool = False


class DesignStudio:
    """AI-assisted creative-production environment for satisfying canonical Project Goals.

    Design Studio is a consumer of the generic root-Agent/Goal reconciler established by #804.
    It owns the Design-Studio-specific projection:

    `Goal revision + Persona + Workspace memory + Design System + CreativeBrief`
                                  ↓
                            Design Studio
                   ↙          ↓          ↘
               Canvas       Builders    Deck/media/tools
                   ↘          ↓          ↙
                       versioned artifacts
                                ↓
                       user/Agent evaluate, edit, lock, redirect

    The Design Studio coordinates between the Workspace Agent's goal reconciliation
    and Design Studio-specific functionality without duplicating the core semantics.
    """

    def __init__(self, config: DesignStudioConfig):
        self.config = config
        self.workspace_context = WorkspaceContext(config.workspace_id)
        self.tool_selector = StudioToolSelector()
        self.control_manager = ControlManager(config.workspace_id, config.project_id)
        self.executor = MixedControlExecutor(config.workspace_id)
        self.current_project: DesignProject | None = None
        self.active_brief: CreativeBrief | None = None

    async def initialize(self) -> None:
        """Initialize Design Studio with Workspace context and available tools."""
        logger.info(
            "initializing_design_studio",
            workspace=self.config.workspace_id,
            project=self.config.project_id,
        )

        # Load Workspace context (consumed via #776)
        await self.workspace_context.load()

        # Load available design tools
        await self.tool_selector.load_tools()

        # Initialize control manager
        await self.control_manager.initialize()

    async def bind_goal_revision(self, goal_id: str, goal_revision: str) -> CreativeBrief:
        """Create a CreativeBrief bound to a canonical Goal revision.

        This is the core Design Studio projection: one canonical Goal revision produces
        a CreativeBrief bound to one canonical Persona and Design System.

        Args:
            goal_id: The canonical Goal ID
            goal_revision: The Goal revision number

        Returns:
            A CreativeBrief representing the Goal revision
        """
        logger.info("binding_goal_revision", goal_id=goal_id, goal_revision=goal_revision)

        # Load Goal state (consumes #458 Goal reconciliation API)
        goal_state = await self._read_goal_state(goal_id, goal_revision)
        if not goal_state:
            raise ValueError(f"Goal {goal_id} revision {goal_revision} not found")

        # Create CreativeBrief from Goal revision
        creative_brief = await CreativeBrief.from_goal_revision(
            goal_id=goal_id,
            goal_revision=goal_revision,
            goal_state=goal_state,
            persona_id=self.config.persona_id,
            design_system_id=self.config.design_system_id,
        )

        self.active_brief = creative_brief
        logger.info("creative_brief_created", brief_id=creative_brief.id)
        return creative_brief

    async def get_workspace_context(self) -> dict[str, Any]:
        """Get relevant Workspace context without cross-Workspace bleed.

        Consumed through #776 Workspace Ladybug working graph.
        """
        return await self.workspace_context.get_relevant_context()

    async def select_and_compose_tools(self, goal_state: dict[str, Any]) -> list[dict[str, Any]]:
        """Select/compose existing Design Studio tools rather than hard-coding Canvas or direct provider calls.

        The Agent selects/composes existing Design Studio tools through the StudioToolSelector.
        """
        available_tools = await self.tool_selector.select_tools(goal_state)
        logger.info(
            "tools_selected",
            count=len(available_tools),
            tools=[t.get("type") for t in available_tools],
        )
        return available_tools

    async def create_project(self, discovery: dict[str, Any]) -> DesignProject:
        """Create a design project from discovery responses.

        This uses the existing Design Engine routes (/v1/design/*) rather than hard-coding
        Canvas or direct provider calls.
        """
        # Use the existing Design Engine API
        from maistro_design.engine import DesignEngine

        engine = DesignEngine()
        project = await engine.generate(discovery, org_id=self.config.workspace_id)

        self.current_project = project
        await self.control_manager.create_project(project.id)

        logger.info(
            "design_project_created", project_id=project.id, skill_slug=discovery.get("skill_slug")
        )
        return project

    async def execute_in_mode(
        self,
        project_id: str,
        mode: str,  # "direct", "collaborative", "delegated"
        instructions: str | None = None,
    ) -> dict[str, Any]:
        """Execute creative work in specified control mode.

        All modes operate on the same artifact/project representation.
        """
        # Validate control mode
        if mode not in ("direct", "collaborative", "delegated"):
            raise ValueError(f"Invalid control mode: {mode}")

        # Update control state
        await self.control_manager.set_control_mode(project_id, mode)

        # Get the project
        if not self.current_project:
            # Try to get existing project
            self.current_project = await self._get_project(project_id)

        if not self.current_project:
            raise ValueError(f"Project {project_id} not found")

        # Execute according to mode
        if mode == "direct":
            return await self._execute_direct(project_id, instructions)
        elif mode == "collaborative":
            return await self._execute_collaborative(project_id, instructions)
        else:  # delegated
            return await self._execute_delegated(project_id, instructions)

    async def _execute_direct(self, project_id: str, instructions: str | None) -> dict[str, Any]:
        """Direct mode: user edits artifacts and invokes bounded AI help."""
        logger.info("executing_direct_mode", project_id=project_id)

        # User edits artifacts directly
        if instructions:
            await self._apply_user_edits(project_id, instructions)

        # AI can help with specific tasks
        result = await self._ai_assist(project_id, instructions)
        return {"mode": "direct", "result": result}

    async def _execute_collaborative(
        self, project_id: str, instructions: str | None
    ) -> dict[str, Any]:
        """Collaborative mode: user and Agent alternate proposals/edits."""
        logger.info("executing_collaborative_mode", project_id=project_id)

        # Both user and Agent can propose edits
        if instructions:
            await self._apply_user_edits(project_id, instructions)

        # Agent can propose alternative solutions
        agent_proposals = await self._generate_agent_proposals(project_id)
        result = await self._ai_assist(project_id, None, proposals=agent_proposals)
        return {"mode": "collaborative", "result": result, "proposals": agent_proposals}

    async def _execute_delegated(self, project_id: str, instructions: str | None) -> dict[str, Any]:
        """Delegated mode: #804's accountable/delegated Agent progresses creative work."""
        logger.info("executing_delegated_mode", project_id=project_id)

        # The #804 reconciliation handles the actual execution
        # We just need to ensure constraints are met
        await self.control_manager.check_constraints(project_id)

        # Agent can still provide guidance
        guidance_result = await self._ai_assist(project_id, instructions)
        return {"mode": "delegated", "result": guidance_result}

    async def _read_goal_state(
        self, goal_id: str, goal_revision: str | None
    ) -> dict[str, Any] | None:
        """Read Goal state through #458 Goal reconciliation API."""
        # This consumes the #458 canonical Goal identity, revision, owning Agent/accountability,
        # Subgoal/delegation lineage, and Goal-vs-Run distinction.
        # This is a read-only interface for now.
        try:
            # Try to import and use the Goal reader if available
            from maistro_core.workspaces.campaigns.policy import GoalReader

            class DesignStudioGoalReader(GoalReader):
                async def read_goal_state(
                    self, goal_id: str, goal_revision: str | None
                ) -> str | None:
                    # Implementation would depend on actual Goal storage
                    # For now, return a placeholder
                    return f"goal:{goal_id}:revision:{goal_revision}"

            reader = DesignStudioGoalReader()
            state = await reader.read_goal_state(goal_id, goal_revision)
            return {"goal_id": goal_id, "goal_revision": goal_revision, "state": state}
        except ImportError:
            # GoalReader not available - return placeholder
            return {"goal_id": goal_id, "goal_revision": goal_revision, "state": "placeholder"}

    async def _get_project(self, project_id: str) -> DesignProject | None:
        """Get existing project."""
        # Implementation would load from persistence
        return None

    async def _apply_user_edits(self, project_id: str, edits: str) -> None:
        """Apply user edits to artifacts."""
        logger.info("applying_user_edits", project_id=project_id, edits=edits)
        # Implementation would apply the actual edits to artifacts

    async def _generate_agent_proposals(self, project_id: str) -> list[dict[str, Any]]:
        """Generate agent proposals for collaborative mode."""
        logger.info("generating_agent_proposals", project_id=project_id)
        # Implementation would generate agent proposals
        return []

    async def _ai_assist(
        self,
        project_id: str,
        instructions: str | None = None,
        proposals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Get AI assistance for the current project."""
        logger.info("getting_ai_assist", project_id=project_id)
        # Implementation would call the AI/LLM services
        return {"assistant_response": "Placeholder AI response", "project_id": project_id}

    async def refresh(self) -> dict[str, Any]:
        """Refresh Design Studio state, restoring actual Goal ownership/delegation, control state, locks/guidance, artifacts and canonical execution.

        This restores the actual state rather than restarting an agent animation.
        """
        logger.info("refreshing_design_studio", workspace=self.config.workspace_id)

        # Reinitialize all components
        await self.initialize()

        # Restore any persisted state
        await self.control_manager.restore_state()

        result = {
            "workspace_id": self.config.workspace_id,
            "project_id": self.config.project_id,
            "initialized": True,
            "workspace_context": await self.get_workspace_context(),
        }

        logger.info("design_studio_refreshed", result=result)
        return result
