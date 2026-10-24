"""Import foreign agent definitions into maistro's portable ``AgentCard`` (SPEC-208 §3).

Import-wide: one adapter per source format (OpenAI Assistant, Claude Code
``.claude/agents/*.md``, ...), each normalizing to the same internal
``AgentCard`` (A2A portable agent description). The ``AgentImporterRegistry``
tries each adapter's ``detect()`` in registration order and applies the first match.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

import yaml

from maistro.agents.catalog import AgentCard


def _as_dict(source: Any) -> dict[str, Any]:
    """Coerce a dict or JSON string into a dict; {} on anything else."""
    if isinstance(source, dict):
        return source
    if isinstance(source, str):
        try:
            data = json.loads(source)
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def split_frontmatter(text: Any) -> tuple[dict[str, Any], str] | None:
    """Split ``--- yaml --- body`` markdown into (frontmatter dict, body)."""
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return None
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        front = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict):
        return None
    return front, parts[2].strip()


@runtime_checkable
class AgentImporter(Protocol):
    format: str

    def detect(self, source: Any) -> bool: ...

    def to_agent_card(self, source: Any) -> AgentCard: ...


def _frontmatter_tools(raw: Any) -> tuple[str, ...]:
    """Normalize a frontmatter ``tools`` field (comma-string or list) to a tuple."""
    if isinstance(raw, str):
        return tuple(t.strip() for t in raw.split(",") if t.strip())
    if isinstance(raw, list):
        return tuple(str(t) for t in raw)
    return ()


def _openai_tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        fn = tool.get("function")
        if isinstance(fn, dict):
            fn_name = fn.get("name")
            if isinstance(fn_name, str):
                return fn_name
        type_ = tool.get("type")
        if isinstance(type_, str):
            return type_
    if isinstance(tool, str):
        return tool
    return ""


def _openai_tools(raw: Any) -> tuple[str, ...]:
    """Extract tool names from an OpenAI Assistant ``tools`` list."""
    if not isinstance(raw, list):
        return ()
    return tuple(n for n in (_openai_tool_name(t) for t in raw) if n)


class OpenAIAssistantImporter:
    """OpenAI Assistants / Agent SDK spec (JSON) -> AgentCard."""

    format = "openai_assistant"

    def detect(self, source: Any) -> bool:
        data = _as_dict(source)
        return data.get("object") == "assistant" or ("instructions" in data and "model" in data)

    def to_agent_card(self, source: Any) -> AgentCard:
        data = _as_dict(source)
        name = str(data.get("name") or data.get("id") or "imported_assistant")
        description = str(data.get("instructions") or data.get("description") or "")
        return AgentCard(
            id=str(data.get("id") or name),
            name=name,
            description=description[:500],
            model=str(data.get("model") or "auto"),
            tools=_openai_tools(data.get("tools", [])),
            scope="imported",
        )


class ClaudeCodeAgentImporter:
    """Claude Code ``.claude/agents/*.md`` (frontmatter + body) -> AgentCard.

    Distinguished from a SKILL.md by the absence of a ``parameters`` key
    (which is what makes a markdown doc a skill, not an agent).
    """

    format = "claude_code_agent"

    def detect(self, source: Any) -> bool:
        split = split_frontmatter(source)
        return split is not None and "name" in split[0] and "parameters" not in split[0]

    def to_agent_card(self, source: Any) -> AgentCard:
        split = split_frontmatter(source)
        if split is None:  # pragma: no cover - guarded by detect()
            raise ValueError("not a Claude Code agent markdown document")
        front, body = split
        name = str(front.get("name", "imported_agent"))
        description = str(front.get("description", "")) or body
        return AgentCard(
            id=name,
            name=name,
            description=description[:500],
            model=str(front.get("model", "auto")),
            tools=_frontmatter_tools(front.get("tools", [])),
            scope="imported",
        )


class AgentImporterRegistry:
    """Try each importer's ``detect()`` in order; apply the first match."""

    def __init__(self, importers: Iterable[AgentImporter] | None = None) -> None:
        self._importers: list[AgentImporter] = (
            list(importers)
            if importers is not None
            else [OpenAIAssistantImporter(), ClaudeCodeAgentImporter()]
        )

    def formats(self) -> list[str]:
        return [imp.format for imp in self._importers]

    def import_agent(self, source: Any) -> AgentCard | None:
        for importer in self._importers:
            if importer.detect(source):
                return importer.to_agent_card(source)
        return None
