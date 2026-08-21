"""Agent/skill format portability (SPEC-208 §3-4): import-wide, export-narrow.

Import from many foreign formats (OpenAI Assistant, Claude Code agents/skills, MCP
manifests) into maistro's internal ``AgentCard`` / ``SkillDefinition``; export to a
single widely-compatible target (MCP manifest + SKILL.md).
"""

from __future__ import annotations

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
    "AgentImporterRegistry",
    "ClaudeCodeAgentImporter",
    "ClaudeCodeSkillImporter",
    "ExportBundle",
    "MCPManifestImporter",
    "OpenAIAssistantImporter",
    "SkillImporter",
    "SkillImporterRegistry",
    "export_agent",
    "sanitize_skill_name",
]
