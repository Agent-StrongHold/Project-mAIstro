"""Tests for the agent/skill portability layer (SPEC-208 §3-4)."""

from __future__ import annotations

import json

from maistro.portability import (
    AgentImporterRegistry,
    ClaudeCodeAgentImporter,
    ClaudeCodeSkillImporter,
    MCPManifestImporter,
    OpenAIAssistantImporter,
    SkillImporterRegistry,
    export_agent,
    sanitize_skill_name,
)
from maistro.skills.parser import parse_skill_file

# --- agent importers -----------------------------------------------------


def test_openai_assistant_imports_to_agent_card():
    src = {
        "object": "assistant",
        "id": "asst_123",
        "name": "Researcher",
        "model": "gpt-4o",
        "instructions": "You research things.",
        "tools": [
            {"type": "function", "function": {"name": "web_search"}},
            {"type": "code_interpreter"},
        ],
    }
    card = OpenAIAssistantImporter().to_agent_card(src)
    assert card.name == "Researcher" and card.model == "gpt-4o"
    assert card.description == "You research things."
    assert card.tools == ("web_search", "code_interpreter")
    assert card.scope == "imported"


def test_openai_assistant_accepts_json_string():
    card = OpenAIAssistantImporter().to_agent_card(
        json.dumps({"instructions": "hi", "model": "m", "name": "A"})
    )
    assert card.name == "A" and card.model == "m"


def test_claude_code_agent_imports_to_agent_card():
    md = """---
name: coder
description: Writes code
model: claude-sonnet
tools: read, write, bash
---
You are a careful coding agent.
"""
    card = ClaudeCodeAgentImporter().to_agent_card(md)
    assert card.name == "coder" and card.model == "claude-sonnet"
    assert card.tools == ("read", "write", "bash")


def test_agent_registry_detects_format():
    reg = AgentImporterRegistry()
    assert "openai_assistant" in reg.formats() and "claude_code_agent" in reg.formats()

    card = reg.import_agent({"object": "assistant", "name": "X", "model": "m"})
    assert card is not None and card.name == "X"
    # A SKILL.md (has `parameters`) is NOT an agent — no importer matches.
    skill_md = "---\nname: s\ndescription: d\nparameters: {type: object}\n---\nbody"
    assert reg.import_agent(skill_md) is None
    assert reg.import_agent(12345) is None


def test_agent_importer_edge_cases():
    imp = ClaudeCodeAgentImporter()
    # Non-string, no-frontmatter, malformed-yaml, and non-dict-frontmatter all → not detected.
    assert imp.detect(123) is False
    assert imp.detect("no frontmatter here") is False
    assert imp.detect("---\njust a scalar\n---\nbody") is False
    assert imp.detect("---\nname: x") is False  # no closing delimiter
    # tools given as a YAML list; missing description falls back to the body.
    md = "---\nname: lister\ntools:\n  - a\n  - b\n---\nBody as description."
    card = imp.to_agent_card(md)
    assert card.tools == ("a", "b") and card.description == "Body as description."
    # tools as neither str nor list (an int) → empty.
    card2 = imp.to_agent_card("---\nname: a\ndescription: d\ntools: 42\n---\nbody")
    assert card2.tools == ()


def test_openai_tools_odd_shapes_ignored():
    card = OpenAIAssistantImporter().to_agent_card(
        {"instructions": "x", "model": "m", "tools": [{"no_name_no_type": 1}, 42, "bash"]}
    )
    # dict-without-name/type → "", int → "", plain string kept.
    assert card.tools == ("bash",)
    # A non-list `tools` field yields no tools.
    card2 = OpenAIAssistantImporter().to_agent_card(
        {"instructions": "x", "model": "m", "tools": "not-a-list"}
    )
    assert card2.tools == ()


# --- skill importers -----------------------------------------------------


def test_claude_code_skill_imports_via_parser():
    skill_md = """---
name: web_search
description: Search the web
parameters:
  type: object
  properties:
    query:
      type: string
---
Search DuckDuckGo and return results.
"""
    skills = ClaudeCodeSkillImporter().to_skill_definitions(skill_md)
    assert len(skills) == 1 and skills[0].name == "web_search"


def test_mcp_manifest_imports_one_skill_per_tool():
    manifest = {
        "name": "filesystem",
        "tools": [
            {"name": "read_file", "description": "Read", "inputSchema": {"type": "object"}},
            {"name": "Write-File!", "description": "Write"},  # name gets sanitized
            "not-a-dict",  # ignored
        ],
    }
    skills = MCPManifestImporter().to_skill_definitions(manifest)
    names = [s.name for s in skills]
    assert names == ["read_file", "write_file"]
    assert skills[0].source == "mcp:filesystem"


def test_skill_registry_picks_the_right_importer():
    reg = SkillImporterRegistry()
    assert reg.import_skills({"tools": [{"name": "grep", "description": "d"}]})[0].name == "grep"
    assert reg.import_skills({"unknown": True}) == []


def test_sanitize_skill_name():
    assert sanitize_skill_name("Read-File!") == "read_file"
    assert sanitize_skill_name("123") == "s_123"
    assert sanitize_skill_name("!!!") == ""


# --- export (round-trip) -------------------------------------------------


def test_export_agent_produces_mcp_manifest_and_reparseable_skill_md():
    # Import an agent + skills, then export — the SKILL.md must re-parse
    # (proves the import -> internal -> export round trip, SPEC-208 AC).
    card = OpenAIAssistantImporter().to_agent_card(
        {"object": "assistant", "name": "My Helper", "model": "gpt-4o", "instructions": "Helps."}
    )
    skills = MCPManifestImporter().to_skill_definitions(
        {"name": "fs", "tools": [{"name": "read_file", "description": "Read a file"}]}
    )
    bundle = export_agent(card, skills)

    # MCP manifest exposes each skill as a tool.
    assert bundle.mcp_manifest["name"] == "My Helper"
    assert bundle.mcp_manifest["tools"][0]["name"] == "read_file"
    assert "inputSchema" in bundle.mcp_manifest["tools"][0]

    # SKILL.md round-trips back through the parser.
    reparsed = parse_skill_file(bundle.skill_md)
    assert reparsed is not None
    assert reparsed.name == "my_helper"  # sanitized from "My Helper"
    assert reparsed.description == "Helps."


def test_export_agent_lists_tools_and_skills_in_body():
    card = ClaudeCodeAgentImporter().to_agent_card(
        "---\nname: builder\ndescription: Builds\ntools: read, write\n---\nbody"
    )
    skills = MCPManifestImporter().to_skill_definitions(
        {"name": "fs", "tools": [{"name": "read_file", "description": "d"}]}
    )
    bundle = export_agent(card, skills)
    assert "Tools: read, write" in bundle.skill_md
    assert "Skills: read_file" in bundle.skill_md
    assert parse_skill_file(bundle.skill_md) is not None


def test_export_agent_with_no_skills_still_valid():
    card = ClaudeCodeAgentImporter().to_agent_card(
        "---\nname: solo\ndescription: A solo agent\n---\nbody"
    )
    bundle = export_agent(card)
    assert bundle.mcp_manifest["tools"] == []
    assert parse_skill_file(bundle.skill_md) is not None
