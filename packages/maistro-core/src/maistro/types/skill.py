"""Skill types: definitions and metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillDefinition:
    """A parsed SKILL.md file."""

    name: str
    description: str = ""
    groups: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    endpoint: str = ""
    auth_key_env: str = ""
    system_prompt: str = ""
    source: str = ""
    trust_tier: str = "t2"


@dataclass(frozen=True)
class SkillMetadata:
    """Metadata for skill marketplace search results."""

    name: str
    description: str = ""
    source_url: str = ""
    author: str = ""
    version: str = ""
    source_type: str = ""
    tags: tuple[str, ...] = ()
    download_count: int = 0
    # SPEC-208: explicit import-adapter format for this catalog entry
    # (e.g. "claude_code_skill", "pi", "mcp_manifest"); None -> auto-detect.
    import_format: str | None = None
