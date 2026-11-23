"""Agent/skill format portability (SPEC-208 §3-4): import-wide, export-narrow.

Import from many foreign formats (OpenAI Assistant, Claude Code agents/skills, MCP
manifests) into maistro's internal ``AgentCard`` / ``SkillDefinition``; export to a
single widely-compatible target (MCP manifest + SKILL.md).
"""

from __future__ import annotations

from maistro.portability.agent_skills import (
    AgentSkillPackage,
    AgentSkillValidationError,
    export_agent_skill_directory,
    load_agent_skill_directory,
)
from maistro.portability.agents import (
    AgentImporter,
    AgentImporterRegistry,
    ClaudeCodeAgentImporter,
    OpenAIAssistantImporter,
)
from maistro.portability.export import ExportBundle, export_agent
from maistro.portability.skills import (
    ClaudeCodeSkillImporter,
    MCPManifestImporter,
    SkillImporter,
    SkillImporterRegistry,
    sanitize_skill_name,
)

__all__ = [
    "AgentImporter",
    "AgentSkillPackage",
    "AgentSkillValidationError",
    "AgentImporterRegistry",
    "ClaudeCodeAgentImporter",
    "ClaudeCodeSkillImporter",
    "ExportBundle",
    "MCPManifestImporter",
    "OpenAIAssistantImporter",
    "SkillImporter",
    "SkillImporterRegistry",
    "export_agent",
    "export_agent_skill_directory",
    "load_agent_skill_directory",
    "sanitize_skill_name",
]
