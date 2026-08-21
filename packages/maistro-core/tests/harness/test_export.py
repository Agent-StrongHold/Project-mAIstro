"""export_agent(): MCP manifest + SKILL.md, and the import->export round trip (SPEC-208)."""

from __future__ import annotations

from maistro.agents.export import MCP_MANIFEST_SCHEMA_VERSION, ExportBundle, export_agent
from maistro.agents.importers.pi import PiAgentImporter
from maistro.skills.importers.claude_code import ClaudeCodeSkillImporter
from maistro.skills.parser import parse_skill_file
from maistro.types.agent import AgentIdentity
from maistro.types.skill import SkillDefinition

SKILL = SkillDefinition(
    name="web_search",
    description="Search the web",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)

PI_AGENT = {
    "kind": "pi.agent",
    "name": "Research-Helper",
    "description": "Finds and summarizes papers",
    "model": {"preferred": "claude-sonnet-4-6"},
    "tools": ["web_search"],
    "instructions": "You are a research assistant. Cite everything.",
}


def test_manifest_shape_and_pinned_schema_version() -> None:
    agent = AgentIdentity(name="helper", description="A helper agent")
    bundle = export_agent(agent, [SKILL])
    assert isinstance(bundle, ExportBundle)
    manifest = bundle.mcp_manifest
    assert manifest["schema_version"] == MCP_MANIFEST_SCHEMA_VERSION
    assert manifest["name"] == "helper"
    assert manifest["capabilities"]["tools"] == {"listChanged": False}
    assert manifest["tools"] == [
        {
            "name": "web_search",
            "description": "Search the web",
            "inputSchema": SKILL.parameters,
        }
    ]


def test_skill_md_reparses_with_native_parser() -> None:
    agent = AgentIdentity(name="helper", description="A helper agent")
    bundle = export_agent(agent, [SKILL])
    parsed = parse_skill_file(bundle.skill_md)
    assert parsed is not None
    assert parsed.name == "helper"
    assert parsed.description == "A helper agent"
    assert "web_search: Search the web" in parsed.system_prompt


def test_skill_md_reparses_for_agent_with_empty_description_and_odd_name() -> None:
    agent = AgentIdentity(name="Ré-Helper 9")
    parsed = parse_skill_file(export_agent(agent, []).skill_md)
    assert parsed is not None
    assert parsed.description  # fallback description supplied


def test_import_export_round_trip_through_internal_representation() -> None:
    """Pi-imported agent + Claude-Code-imported skill -> export_agent -> both
    artifacts valid; proves the round trip through AgentIdentity/SkillDefinition."""
    agent = PiAgentImporter().to_agent_config(PI_AGENT)
    skill_md_source = (
        "---\nname: web_search\ndescription: Search the web\n"
        "parameters:\n  type: object\n  properties:\n    query:\n      type: string\n"
        "---\n\nSearch and cite.\n"
    )
    skills = ClaudeCodeSkillImporter().to_skill_definitions(skill_md_source)
    bundle = export_agent(agent, skills)

    manifest = bundle.mcp_manifest
    assert manifest["schema_version"] == MCP_MANIFEST_SCHEMA_VERSION
    assert manifest["name"] == "research_helper"
    assert [t["name"] for t in manifest["tools"]] == ["web_search"]

    parsed = parse_skill_file(bundle.skill_md)
    assert parsed is not None
    assert parsed.name == "research_helper"
    assert "Cite everything." in parsed.system_prompt  # Pi instructions carried through
