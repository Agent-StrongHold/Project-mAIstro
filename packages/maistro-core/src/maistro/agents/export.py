"""Agent export (SPEC-208): one target format — MCP manifest + SKILL.md.

Import wide, export narrow: regardless of how an agent entered maistro
(native, Pi, OpenClaw, ...), it is published as (1) an MCP server manifest
exposing its skills as MCP tools, and (2) a SKILL.md that maistro's own
skills/parser.py — and any SKILL.md-aware harness — can re-parse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from maistro.agents.importers.pi import sanitize_agent_name

if TYPE_CHECKING:
    from maistro.types.agent import AgentIdentity
    from maistro.types.skill import SkillDefinition

# Pinned MCP schema (protocol revision) the exported manifest targets.
# Upgrade path: bump this constant + adjust the manifest shape in one commit;
# consumers pin on `schema_version` in the manifest.
MCP_MANIFEST_SCHEMA_VERSION = "2025-06-18"


@dataclass(frozen=True)
class ExportBundle:
    """The single export artifact: MCP server manifest + SKILL.md text."""

    mcp_manifest: dict[str, Any]
    skill_md: str


def export_agent(agent: AgentIdentity, skills: list[SkillDefinition]) -> ExportBundle:
    """Publish `agent` + its skills as an MCP server manifest and a SKILL.md."""
    manifest: dict[str, Any] = {
        "schema_version": MCP_MANIFEST_SCHEMA_VERSION,
        "name": agent.name,
        "version": agent.version,
        "description": agent.description,
        "capabilities": {"tools": {"listChanged": False}},
        "tools": [
            {
                "name": skill.name,
                "description": skill.description,
                "inputSchema": skill.parameters,
            }
            for skill in skills
        ],
    }
    return ExportBundle(mcp_manifest=manifest, skill_md=_render_skill_md(agent, skills))


def _render_skill_md(agent: AgentIdentity, skills: list[SkillDefinition]) -> str:
    name = sanitize_agent_name(agent.name)
    description = agent.description.strip() or f"Exported maistro agent {name}"
    frontmatter: dict[str, Any] = {
        "name": name,
        "description": description[:500],
        "groups": ["agent", "exported"],
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task or message for this agent",
                }
            },
            "required": ["task"],
        },
        "trust_tier": agent.trust_tier,
    }
    instructions = str(agent.model_constraints.get("instructions", "")).strip()
    body_parts = [description]
    if instructions:
        body_parts.append(instructions)
    if skills:
        skill_lines = "\n".join(f"- {s.name}: {s.description}" for s in skills)
        body_parts.append(f"Available skills:\n{skill_lines}")
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
    return f"---\n{yaml_block}---\n\n" + "\n\n".join(body_parts) + "\n"
