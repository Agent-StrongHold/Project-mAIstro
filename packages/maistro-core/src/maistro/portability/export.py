"""Export a maistro agent to the single, widely-compatible target (SPEC-208 §4).

Export-narrow: regardless of how an agent was imported (native, Pi, OpenClaw,
OpenAI, ...), there is exactly one export path — an MCP server manifest exposing
the agent's skills as MCP tools, plus a ``SKILL.md`` describing the agent that
any SKILL.md-aware harness (and ``skills/parser.py``) can re-parse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from maistro.agents.catalog import AgentCard
from maistro.portability.skills import sanitize_skill_name
from maistro.types.skill import SkillDefinition


@dataclass(frozen=True)
class ExportBundle:
    mcp_manifest: dict[str, Any]
    skill_md: str


def _mcp_manifest(agent: AgentCard, skills: list[SkillDefinition]) -> dict[str, Any]:
    return {
        "name": agent.name,
        "version": agent.version,
        "description": agent.description,
        "tools": [
            {
                "name": skill.name,
                "description": skill.description,
                "inputSchema": skill.parameters,
            }
            for skill in skills
        ],
    }


def _skill_md(agent: AgentCard, skills: list[SkillDefinition]) -> str:
    description = agent.description or f"Exported agent {agent.name}"
    frontmatter = {
        "name": sanitize_skill_name(agent.name) or "exported_agent",
        "description": description[:500],
        "parameters": {"type": "object", "properties": {"task": {"type": "string"}}},
        "trust_tier": agent.trust_tier,
    }
    body_lines = [description, ""]
    if agent.tools:
        body_lines.append("Tools: " + ", ".join(agent.tools))
    if skills:
        body_lines.append("Skills: " + ", ".join(s.name for s in skills))
    body = "\n".join(body_lines)
    return "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body


def export_agent(agent: AgentCard, skills: list[SkillDefinition] | None = None) -> ExportBundle:
    """Produce the MCP manifest + SKILL.md export bundle for ``agent``."""
    skills = skills or []
    return ExportBundle(
        mcp_manifest=_mcp_manifest(agent, skills),
        skill_md=_skill_md(agent, skills),
    )
