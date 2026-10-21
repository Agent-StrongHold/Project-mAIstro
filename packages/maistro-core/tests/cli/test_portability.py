"""Tests for `maistro portability` (maistro.cli._portability).

These exercise the shipped Typer app — the same object the `maistro` console
script dispatches to — because the point of the #34 CONNECT tranche was that
the ADR-101 adapters become callable from a product entry point, not merely
importable. The unit behavior of the adapters themselves is covered in
`tests/portability/test_portability.py`; what is new here is the command
surface: file/stdin reading, output writing, format detection failures, and
the import → export → re-import round trip.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from maistro.cli._portability import app
from maistro.portability.agents import split_frontmatter

runner = CliRunner()


def _diagnostics(result: object) -> str:
    """stdout + stderr, whitespace-collapsed: error text goes to stderr (Click 8
    separates the streams) and rich hard-wraps it mid-sentence."""
    return " ".join((str(result.output) + str(result.stderr)).split())


OPENAI_ASSISTANT = json.dumps(
    {
        "object": "assistant",
        "id": "asst_1",
        "name": "Researcher",
        "model": "gpt-4o",
        "instructions": "You research things.",
        "tools": [{"type": "function", "function": {"name": "web_search"}}],
    }
)

CLAUDE_AGENT_MD = """---
name: coder
description: Writes code
model: claude-sonnet
tools: read, write
---
Careful coding agent.
"""

MCP_MANIFEST = json.dumps(
    {
        "name": "toolshed",
        "tools": [
            {
                "name": "Web Search",
                "description": "Search the web",
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
            {"name": "9lives", "description": "name needs sanitizing"},
        ],
    }
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestFormats:
    def test_lists_every_registered_import_format(self) -> None:
        result = runner.invoke(app, ["formats"])
        assert result.exit_code == 0
        for fmt in ("openai_assistant", "claude_code_agent", "claude_code_skill", "mcp_manifest"):
            assert fmt in result.output


class TestImportAgent:
    def test_openai_assistant_json_file_imports(self, tmp_path: Path) -> None:
        src = _write(tmp_path, "assistant.json", OPENAI_ASSISTANT)
        result = runner.invoke(app, ["import-agent", str(src)])
        assert result.exit_code == 0, result.output
        card = json.loads(result.output)
        assert card["name"] == "Researcher"
        assert card["model"] == "gpt-4o"
        assert card["tools"] == ["web_search"]
        assert card["scope"] == "imported"

    def test_claude_code_markdown_imports(self, tmp_path: Path) -> None:
        src = _write(tmp_path, "agent.md", CLAUDE_AGENT_MD)
        result = runner.invoke(app, ["import-agent", str(src), "-o", str(tmp_path / "card.json")])
        assert result.exit_code == 0, result.output
        card = json.loads((tmp_path / "card.json").read_text())
        assert card["name"] == "coder"
        assert card["tools"] == ["read", "write"]

    def test_stdin_source_is_read(self) -> None:
        result = runner.invoke(app, ["import-agent", "-"], input=OPENAI_ASSISTANT)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["name"] == "Researcher"

    def test_a_skill_md_is_not_an_agent(self, tmp_path: Path) -> None:
        skill_md = "---\nname: s\ndescription: d\nparameters: {type: object}\n---\nbody"
        src = _write(tmp_path, "SKILL.md", skill_md)
        result = runner.invoke(app, ["import-agent", str(src)])
        assert result.exit_code == 1
        assert "no agent importer recognizes" in _diagnostics(result)

    def test_missing_file_fails(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["import-agent", str(tmp_path / "nope.json")])
        assert result.exit_code == 1
        assert "cannot read" in _diagnostics(result)


class TestImportSkills:
    def test_mcp_manifest_imports_with_sanitized_names(self, tmp_path: Path) -> None:
        src = _write(tmp_path, "manifest.json", MCP_MANIFEST)
        result = runner.invoke(app, ["import-skills", str(src)])
        assert result.exit_code == 0, result.output
        skills = json.loads(result.output)
        assert [s["name"] for s in skills] == ["web_search", "s_9lives"]
        assert skills[0]["source"] == "mcp:toolshed"

    def test_detected_but_empty_manifest_is_not_an_error(self, tmp_path: Path) -> None:
        # Every tool name sanitizes away: recognized format, zero skills.
        src = _write(tmp_path, "empty.json", json.dumps({"tools": [{"name": "!!!"}]}))
        result = runner.invoke(app, ["import-skills", str(src)])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == []

    def test_unrecognized_document_fails(self, tmp_path: Path) -> None:
        src = _write(tmp_path, "agent.md", CLAUDE_AGENT_MD)
        result = runner.invoke(app, ["import-skills", str(src)])
        assert result.exit_code == 1
        assert "no skill importer recognizes" in _diagnostics(result)

    def test_output_option_writes_a_file(self, tmp_path: Path) -> None:
        src = _write(tmp_path, "manifest.json", MCP_MANIFEST)
        out = tmp_path / "skills.json"
        result = runner.invoke(app, ["import-skills", str(src), "-o", str(out)])
        assert result.exit_code == 0, result.output
        assert json.loads(out.read_text())[0]["name"] == "web_search"


class TestExport:
    def test_import_export_reimport_round_trip(self, tmp_path: Path) -> None:
        """The pipeline the CLI exists for: foreign agent in, portable bundle out,
        and the written SKILL.md re-imports through the same shipped command."""
        card_src = _write(tmp_path, "assistant.json", OPENAI_ASSISTANT)
        imported = tmp_path / "card.json"
        assert (
            runner.invoke(app, ["import-agent", str(card_src), "-o", str(imported)]).exit_code == 0
        )

        skills_src = _write(tmp_path, "manifest.json", MCP_MANIFEST)
        skilldefs = tmp_path / "skills.json"
        assert (
            runner.invoke(app, ["import-skills", str(skills_src), "-o", str(skilldefs)]).exit_code
            == 0
        )

        out_dir = tmp_path / "bundle"
        result = runner.invoke(
            app,
            ["export", str(imported), "--skills", str(skilldefs), "--out-dir", str(out_dir)],
        )
        assert result.exit_code == 0, result.output

        manifest = json.loads((out_dir / "mcp-manifest.json").read_text())
        assert manifest["name"] == "Researcher"
        assert [tool["name"] for tool in manifest["tools"]] == ["web_search", "s_9lives"]

        skill_md = (out_dir / "SKILL.md").read_text()
        front, _body = split_frontmatter(skill_md)
        assert front is not None
        assert front["name"] == "researcher"
        assert front["trust_tier"] == "t2"

        reimport = runner.invoke(app, ["import-skills", str(out_dir / "SKILL.md")])
        assert reimport.exit_code == 0, reimport.output
        round_tripped = json.loads(reimport.output)
        assert round_tripped[0]["name"] == "researcher"
        assert round_tripped[0]["parameters"] == front["parameters"]

    def test_unknown_agent_field_is_named(self, tmp_path: Path) -> None:
        src = _write(tmp_path, "card.json", json.dumps({"id": "x", "name": "x", "bogus": 1}))
        result = runner.invoke(app, ["export", str(src)])
        assert result.exit_code == 1
        assert "bogus" in _diagnostics(result)

    def test_missing_required_field_is_named(self, tmp_path: Path) -> None:
        src = _write(tmp_path, "card.json", json.dumps({"id": "x"}))
        result = runner.invoke(app, ["export", str(src)])
        assert result.exit_code == 1
        assert "name" in _diagnostics(result)

    def test_a_foreign_assistant_document_is_not_an_agent_card(self, tmp_path: Path) -> None:
        """Export takes an AgentCard, not a foreign format: the rejected OpenAI
        keys are named rather than silently dropped."""
        src = _write(tmp_path, "assistant.json", OPENAI_ASSISTANT)
        result = runner.invoke(app, ["export", str(src)])
        assert result.exit_code == 1
        assert "instructions" in _diagnostics(result)

    def test_invalid_skills_payload_is_rejected(self, tmp_path: Path) -> None:
        card = _write(tmp_path, "card.json", json.dumps({"id": "x", "name": "x"}))
        skills = _write(tmp_path, "skills.json", json.dumps({"not": "a list"}))
        result = runner.invoke(app, ["export", str(card), "--skills", str(skills)])
        assert result.exit_code == 1
        assert "JSON array" in _diagnostics(result)

    def test_skill_with_unknown_field_is_named(self, tmp_path: Path) -> None:
        card = _write(tmp_path, "card.json", json.dumps({"id": "x", "name": "x"}))
        skills = _write(tmp_path, "skills.json", json.dumps([{"name": "s", "nope": True}]))
        result = runner.invoke(app, ["export", str(card), "--skills", str(skills)])
        assert result.exit_code == 1
        assert "nope" in _diagnostics(result)

    def test_non_json_agent_file_fails(self, tmp_path: Path) -> None:
        src = _write(tmp_path, "agent.md", CLAUDE_AGENT_MD)
        result = runner.invoke(app, ["export", str(src)])
        assert result.exit_code == 1
        assert "not valid JSON" in _diagnostics(result)
