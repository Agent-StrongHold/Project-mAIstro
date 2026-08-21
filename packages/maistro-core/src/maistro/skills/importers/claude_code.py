"""Claude Code SKILL.md importer (SPEC-208).

Thin wrapper: maistro's native skill format IS the Claude Code SKILL.md shape
(YAML frontmatter + markdown body), so this delegates to skills/parser.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.skills.parser import parse_skill_file

if TYPE_CHECKING:
    from maistro.types.skill import SkillDefinition


class ClaudeCodeSkillImporter:
    """Imports Claude Code SKILL.md content into SkillDefinition."""

    @property
    def format(self) -> str:
        return "claude_code_skill"

    def detect(self, source: dict[str, Any] | str) -> bool:
        if not isinstance(source, str):
            return False
        return source.startswith("---\n") and parse_skill_file(source) is not None

    def to_skill_definitions(self, source: dict[str, Any] | str) -> list[SkillDefinition]:
        if not isinstance(source, str):
            return []
        skill = parse_skill_file(source, source="import:claude_code_skill")
        return [skill] if skill is not None else []
