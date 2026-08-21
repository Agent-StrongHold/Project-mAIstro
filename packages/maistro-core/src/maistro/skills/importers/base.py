"""SkillImporter protocol (SPEC-208)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro.types.skill import SkillDefinition


@runtime_checkable
class SkillImporter(Protocol):
    """Translates a foreign skill definition into maistro SkillDefinitions.

    ``format`` names the source format ("claude_code_skill" | "mcp_manifest" |
    "openai_tool" | ...). ``detect()`` must be cheap and never raise;
    ``to_skill_definitions()`` returns [] for unparseable input.
    """

    @property
    def format(self) -> str: ...

    def detect(self, source: dict[str, Any] | str) -> bool: ...

    def to_skill_definitions(self, source: dict[str, Any] | str) -> list[SkillDefinition]: ...
