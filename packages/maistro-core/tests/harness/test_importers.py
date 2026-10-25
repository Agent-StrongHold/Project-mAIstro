"""AgentImporter/SkillImporter round-trips + ImporterRegistry (SPEC-208)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from maistro.agents.importers import (
    AgentImporter,
    ImporterRegistry,
    PiAgentImporter,
    agent_identity_to_node_template,
)
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
    assert agent.name == "research_helper"
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


# --- canonical NodeTemplate projection ---


def test_agent_identity_projects_to_workspace_node_template_without_guessing_runtime() -> None:
    agent = PiAgentImporter().to_agent_config(PI_AGENT)
    template = agent_identity_to_node_template(
        agent,
        workspace_id="workspace-1",
        node_type="agent.runtime_selected_by_caller",
        parameters={"adapter": "chosen-elsewhere"},
    )

    assert template.workspace_id == "workspace-1"
    assert template.name == "research_helper"
    assert template.node_type == "agent.runtime_selected_by_caller"
    assert template.parameters == {"adapter": "chosen-elsewhere"}
    assert template.binding_ids == []
    assert template.permissions == {}
    assert template.policies == {}

    source = template.metadata["source_import_provenance"]
    assert source["source_format"] == "pi"
    assert source["source_definition"] == "AgentIdentity"
    assert source["source_name"] == "research_helper"
    assert len(source["source_hash"]) == 64

    snapshot = template.metadata["legacy_definition_snapshot"]
    assert snapshot["model"] == "claude-sonnet-4-6"
    assert snapshot["tools"] == ["web_search", "document_reader"]
    assert snapshot["model_constraints"]["harness_runner"] == "pi"
    assert snapshot["model_constraints"]["instructions"] == PI_AGENT["instructions"]


def test_native_legacy_identity_gets_explicit_legacy_source_format() -> None:
    agent = replace(PiAgentImporter().to_agent_config(PI_AGENT), provenance="")
    template = agent_identity_to_node_template(
        agent,
        workspace_id="workspace-1",
        node_type="agent.explicit",
    )
    assert template.metadata["source_import_provenance"]["source_format"] == (
        "legacy_agent_identity"
    )


@pytest.mark.parametrize(
    "forbidden",
    [
        "trust_tier",
        "priority_tier",
        "provenance",
        "ai_reviewed",
        "ai_review_clean",
        "admin_reviewed",
        "admin_reviewed_by",
        "user_reviewed",
        "active",
    ],
)
def test_projection_does_not_launder_legacy_authority_or_live_state(forbidden: str) -> None:
    agent = PiAgentImporter().to_agent_config(PI_AGENT)
    template = agent_identity_to_node_template(
        agent,
        workspace_id="workspace-1",
        node_type="agent.explicit",
    )

    snapshot = template.metadata["legacy_definition_snapshot"]
    assert forbidden not in snapshot
    assert forbidden not in template.parameters
    assert forbidden not in template.permissions
    assert forbidden not in template.policies


def test_projected_template_instantiates_with_canonical_template_provenance() -> None:
    agent = PiAgentImporter().to_agent_config(PI_AGENT)
    template = agent_identity_to_node_template(
        agent,
        workspace_id="workspace-1",
        node_type="agent.explicit",
    )
    node = template.instantiate()

    assert node.source_template is not None
    assert node.source_template.template_id == template.template_id
    assert node.source_template.template_version == template.version
    assert node.source_template.template_hash == template.content_hash
    assert node.metadata["source_import_provenance"]["source_format"] == "pi"


def test_projection_requires_explicit_workspace_and_node_kind() -> None:
    agent = PiAgentImporter().to_agent_config(PI_AGENT)
    with pytest.raises(ValueError, match="workspace_id"):
        agent_identity_to_node_template(agent, workspace_id=" ", node_type="agent.explicit")
    with pytest.raises(ValueError, match="node_type"):
        agent_identity_to_node_template(agent, workspace_id="workspace-1", node_type=" ")


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
