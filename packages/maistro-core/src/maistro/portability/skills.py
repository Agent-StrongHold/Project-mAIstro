"""Import foreign skill/tool definitions into maistro ``SkillDefinition``s (SPEC-208 §3).

Import-wide: Claude Code ``SKILL.md`` (reusing ``skills/parser.py``) and MCP
server/tool manifests, normalized to the internal ``SkillDefinition``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from maistro.portability.agents import _as_dict, split_frontmatter
from maistro.skills.parser import parse_skill_file, validate_skill_name
from maistro.types.skill import SkillDefinition

_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def sanitize_skill_name(name: str) -> str:
    """Best-effort coerce an arbitrary tool name to a valid skill name, or ''."""
    slug = re.sub(r"[^a-z0-9_]", "_", name.strip().lower()).strip("_")
    if not slug:
        return ""
    if not slug[0].isalpha():
        slug = f"s_{slug}"
    slug = slug[:51]
    return slug if validate_skill_name(slug) else ""


@runtime_checkable
class SkillImporter(Protocol):
    format: str

    def detect(self, source: Any) -> bool: ...

    def to_skill_definitions(self, source: Any) -> list[SkillDefinition]: ...


class ClaudeCodeSkillImporter:
    """Claude Code ``SKILL.md`` frontmatter+body -> SkillDefinition."""

    format = "claude_code_skill"

    def detect(self, source: Any) -> bool:
        split = split_frontmatter(source)
        return split is not None and "parameters" in split[0]

    def to_skill_definitions(self, source: Any) -> list[SkillDefinition]:
        skill = parse_skill_file(source) if isinstance(source, str) else None
        return [skill] if skill is not None else []


class MCPManifestImporter:
    """An MCP server/tool manifest (``{"tools": [...]}``) -> one SkillDefinition per tool."""

    format = "mcp_manifest"

    def detect(self, source: Any) -> bool:
        return isinstance(_as_dict(source).get("tools"), list)

    def to_skill_definitions(self, source: Any) -> list[SkillDefinition]:
        data = _as_dict(source)
        server = str(data.get("name", "mcp"))
        out: list[SkillDefinition] = []
        for tool in data.get("tools", []):
            if not isinstance(tool, dict):
                continue
            name = sanitize_skill_name(str(tool.get("name", "")))
            if not name:
                continue
            schema = tool.get("inputSchema") or tool.get("input_schema")
            out.append(
                SkillDefinition(
                    name=name,
                    description=str(tool.get("description", ""))[:500],
                    parameters=schema if isinstance(schema, dict) else dict(_EMPTY_SCHEMA),
                    source=f"mcp:{server}",
                )
            )
        return out


class SkillImporterRegistry:
    """Try each importer's ``detect()`` in order; apply the first match."""

    def __init__(self, importers: Iterable[SkillImporter] | None = None) -> None:
        self._importers: list[SkillImporter] = (
            list(importers)
            if importers is not None
            else [ClaudeCodeSkillImporter(), MCPManifestImporter()]
        )

    def formats(self) -> list[str]:
        return [imp.format for imp in self._importers]

    def import_skills(self, source: Any) -> list[SkillDefinition]:
        for importer in self._importers:
            if importer.detect(source):
                return importer.to_skill_definitions(source)
        return []
