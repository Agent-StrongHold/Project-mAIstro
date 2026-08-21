"""AgentImporter/SkillImporter round-trips + ImporterRegistry (SPEC-208)."""

from __future__ import annotations

from maistro.agents.importers import AgentImporter, ImporterRegistry, PiAgentImporter
from maistro.agents.importers.base import default_importer_registry
from maistro.skills.importers import ClaudeCodeSkillImporter, SkillImporter
from maistro.skills.parser import parse_skill_file

SKILL_MD = """---
name: web_search
description: Search the web
groups: [search, web]
parameters:
  type: object
  properties:
    query:
      type: string
  required: [query]
trust_tier: t2
---

You are a web search tool. Cite your sources.
"""

PI_AGENT = {
    "kind": "pi.agent",
    "name": "Research-Helper",
    "description": "Finds and summarizes papers",
    "model": {"preferred": "claude-sonnet-4-6"},
    "tools": ["web_search", "document_reader"],
    "instructions": "You are a research assistant. Cite everything.",
    "trust_tier": "t2",
}


# --- Claude Code SKILL.md importer ---


def test_claude_code_importer_conforms_and_detects() -> None:
    importer = ClaudeCodeSkillImporter()
    assert isinstance(importer, SkillImporter)
    assert importer.format == "claude_code_skill"
    assert importer.detect(SKILL_MD) is True
    assert importer.detect("just markdown") is False
    assert importer.detect({"not": "a string"}) is False


def test_claude_code_importer_roundtrip() -> None:
    skills = ClaudeCodeSkillImporter().to_skill_definitions(SKILL_MD)
    assert len(skills) == 1
    skill = skills[0]
    reference = parse_skill_file(SKILL_MD)
    assert reference is not None
    assert skill.name == reference.name == "web_search"
    assert skill.description == reference.description
    assert skill.parameters == reference.parameters
    assert skill.groups == ("search", "web")
    assert "web search tool" in skill.system_prompt


def test_claude_code_importer_invalid_returns_empty() -> None:
    assert ClaudeCodeSkillImporter().to_skill_definitions("---\nbroken") == []


# --- Pi agent importer ---


def test_pi_importer_conforms_and_detects() -> None:
    importer = PiAgentImporter()
    assert isinstance(importer, AgentImporter)
    assert importer.format == "pi"
    assert importer.detect(PI_AGENT) is True
    assert importer.detect({"kind": "openclaw.agent", "name": "x"}) is False
    assert importer.detect("not yaml: [") is False


def test_pi_importer_roundtrip() -> None:
    agent = PiAgentImporter().to_agent_config(PI_AGENT)
    assert agent.name == "research_helper"  # sanitized to maistro name shape
    assert agent.description == "Finds and summarizes papers"
    assert agent.model == "claude-sonnet-4-6"
    assert agent.tools == ("web_search", "document_reader")
    assert agent.trust_tier == "t2"
    assert agent.model_constraints["harness_runner"] == "pi"
    assert agent.model_constraints["instructions"] == PI_AGENT["instructions"]
    assert agent.provenance == "import:pi"


def test_pi_importer_accepts_yaml_string() -> None:
    source = "kind: pi.agent\nname: helper\ndescription: d\nmodel: auto\ntools: [web_search]\n"
    assert PiAgentImporter().detect(source) is True
    agent = PiAgentImporter().to_agent_config(source)
    assert agent.name == "helper"
    assert agent.model == "auto"


# --- ImporterRegistry ---


def test_registry_first_detect_match_wins() -> None:
    registry = default_importer_registry()
    assert registry.agent_formats() == ["pi"]
    assert registry.skill_formats() == ["claude_code_skill"]

    agent = registry.import_agent(PI_AGENT)
    assert agent is not None and agent.name == "research_helper"

    skills = registry.import_skills(SKILL_MD)
    assert [s.name for s in skills] == ["web_search"]


def test_registry_no_match_returns_none_or_empty() -> None:
    registry = default_importer_registry()
    assert registry.import_agent({"kind": "unknown"}) is None
    assert registry.import_skills("plain text") == []


def test_registry_explicit_import_format_skips_detection() -> None:
    registry = ImporterRegistry()
    registry.register_skill_importer(ClaudeCodeSkillImporter())
    skills = registry.import_skills(SKILL_MD, import_format="claude_code_skill")
    assert len(skills) == 1
    assert registry.import_skills(SKILL_MD, import_format="mcp_manifest") == []
