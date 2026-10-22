"""Studio tool selection and composition for Design Studio.

The Agent selects/composes existing Design Studio tools rather than hard-coding
Canvas or direct provider calls. Tools are used through Capability -> Provider ->
Binding -> Invocation with governed effect paths.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


class StudioToolSelector:
    """Select and compose Design Studio tools for creative work.

    The Agent uses this to select/compose existing Design Studio tools rather than
    hard-coding Canvas or direct provider calls. Physical execution remains canonical
    Graph -> Run -> NodeRun -> Attempt.
    """

    def __init__(self):
        self._tools: dict[str, Any] = {}
        self._loaded = False

    async def load_tools(self) -> None:
        """Load available Design Studio tools."""
        logger.info("loading_studio_tools")

        # Define the core Design Studio tools
        self._tools = {
            "canvas": {
                "type": "visual_composition",
                "category": "fixed_page",
                "description": "Fixed-page/visual composition for Canvas",
                "capabilities": ["layout", "design", "generation"],
                "supported_formats": ["pdf", "png", "svg"],
            },
            "builders": {
                "type": "code_generation",
                "category": "code_web",
                "description": "Code generation and web development builders",
                "capabilities": ["code", "web", "api"],
                "supported_formats": ["javascript", "python", "html"],
            },
            "deck_builder": {
                "type": "presentation",
                "category": "presentation",
                "description": "Presentation and slide generation",
                "capabilities": ["slides", "layout", "design"],
                "supported_formats": ["pptx", "pdf", "html"],
            },
            "media_provider": {
                "type": "media_generation",
                "category": "media",
                "description": "Image and media generation provider",
                "capabilities": ["image", "video", "audio"],
                "supported_formats": ["jpg", "png", "mp4", "wav"],
            },
            "editor": {
                "type": "content_editor",
                "category": "text",
                "description": "Rich text and content editing",
                "capabilities": ["editor", "formatting", "revision"],
                "supported_formats": ["markdown", "html", "docx"],
            },
            "creative_writer": {
                "type": "creative_writing",
                "category": "content",
                "description": "Creative writing and copywriting",
                "capabilities": ["copywriting", "storytelling", "marketing"],
                "supported_formats": ["copy", "story", "headline"],
            },
        }

        self._loaded = True
        logger.info("studio_tools_loaded", tool_count=len(self._tools))

    async def select_tools(self, goal_state: dict[str, Any]) -> list[dict[str, Any]]:
        """Select tools based on Goal state and requirements.

        Args:
            goal_state: The Goal state containing requirements and constraints

        Returns:
            List of selected tool configurations
        """
        if not self._loaded:
            await self.load_tools()

        logger.info("selecting_tools_for_goal", goal_state_keys=list(goal_state.keys()))

        # Extract requirements from Goal state
        requirements = self._extract_requirements(goal_state)

        # Select appropriate tools based on requirements
        selected_tools = []

        # Always include Canvas for visual work (common requirement)
        selected_tools.append(
            {
                **self._tools["canvas"],
                "priority": requirements.get("visual", 1),
                "required": True,
            }
        )

        # Add Builders for code/web work if needed
        if requirements.get("code_web", 0) > 0:
            selected_tools.append(
                {
                    **self._tools["builders"],
                    "priority": requirements.get("code_web", 1),
                    "required": False,
                }
            )

        # Add Deck Builder for presentation work if needed
        if requirements.get("presentation", 0) > 0:
            selected_tools.append(
                {
                    **self._tools["deck_builder"],
                    "priority": requirements.get("presentation", 1),
                    "required": False,
                }
            )

        # Add Media Provider for media work if needed
        if requirements.get("media", 0) > 0:
            selected_tools.append(
                {
                    **self._tools["media_provider"],
                    "priority": requirements.get("media", 1),
                    "required": False,
                }
            )

        # Add Editor for content work if needed
        if requirements.get("content", 0) > 0:
            selected_tools.append(
                {
                    **self._tools["editor"],
                    "priority": requirements.get("content", 1),
                    "required": False,
                }
            )

        # Add Creative Writer for copywriting if needed
        if requirements.get("copywriting", 0) > 0:
            selected_tools.append(
                {
                    **self._tools["creative_writer"],
                    "priority": requirements.get("copywriting", 1),
                    "required": False,
                }
            )

        # Sort by priority and filter by requirement
        selected_tools.sort(key=lambda t: t["priority"], reverse=True)

        # Only include tools that meet the requirements
        final_tools = [
            tool
            for tool in selected_tools
            if tool.get("required", False)
            or tool["priority"] >= requirements.get("min_priority", 1)
        ]

        logger.info(
            "tools_selected", count=len(final_tools), tools=[t["type"] for t in final_tools]
        )
        return final_tools

    def _extract_requirements(self, goal_state: dict[str, Any]) -> dict[str, int]:
        """Extract requirements from Goal state to guide tool selection."""
        requirements = {
            "visual": 1,  # Canvas is always prioritized for visual work
            "code_web": 0,
            "presentation": 0,
            "media": 0,
            "content": 0,
            "copywriting": 0,
            "min_priority": 1,
        }

        # Analyze Goal state to determine requirements
        subject = goal_state.get("subject", "").lower()
        outcome = goal_state.get("outcome", "").lower()
        channel = goal_state.get("channel", "").lower()

        # Determine requirements based on Goal analysis
        if any(keyword in subject for keyword in ["code", "website", "app", "software"]):
            requirements["code_web"] = 3

        if any(keyword in subject for keyword in ["slide", "presentation", "deck"]):
            requirements["presentation"] = 3

        if any(keyword in subject for keyword in ["image", "photo", "picture", "video"]):
            requirements["media"] = 3

        if any(keyword in subject for keyword in ["text", "content", "article", "blog"]):
            requirements["content"] = 2

        if any(keyword in outcome for keyword in ["copy", "marketing", "sales"]):
            requirements["copywriting"] = 2

        if channel in ["reel", "vertical", "short"]:
            requirements["visual"] = 2

        return requirements

    async def get_tool_by_type(self, tool_type: str) -> dict[str, Any] | None:
        """Get a specific tool by type."""
        if not self._loaded:
            await self.load_tools()

        return self._tools.get(tool_type)

    async def get_all_tools(self) -> dict[str, Any]:
        """Get all available tools."""
        if not self._loaded:
            await self.load_tools()

        return self._tools.copy()
