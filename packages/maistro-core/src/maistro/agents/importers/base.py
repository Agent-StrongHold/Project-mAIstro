"""AgentImporter protocol + ImporterRegistry (SPEC-208).

The spec's ``to_agent_config()`` targets maistro's internal per-agent spec
type. That type is ``maistro.types.agent.AgentIdentity`` — the name
``maistro.types.AgentConfig`` denotes the *root configuration* object, not an
agent definition, so importers return ``AgentIdentity`` (deliberate deviation
from the spec's type name; the method name is kept).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro.skills.importers.base import SkillImporter
    from maistro.types.agent import AgentIdentity
    from maistro.types.skill import SkillDefinition

logger = logging.getLogger("maistro.agents.importers")


@runtime_checkable
class AgentImporter(Protocol):
    """Translates a foreign agent definition into an AgentIdentity.

    ``format`` names the source format ("pi" | "openclaw" | "claude_code" |
    "codex" | "openai_assistant"). ``detect()`` must be cheap and never raise;
    ``to_agent_config()`` raises ValueError on unparseable input.
    """

    @property
    def format(self) -> str: ...

    def detect(self, source: dict[str, Any] | str) -> bool: ...

    def to_agent_config(self, source: dict[str, Any] | str) -> AgentIdentity: ...


class ImporterRegistry:
    """Ordered importer catalog (mirrors CapabilityRegistry's shape, unkeyed by slot).

    Tries each importer's detect() in registration order and applies the first
    match. ``import_format`` (SkillMetadata.import_format) can name a format
    explicitly to skip detection.
    """

    def __init__(self) -> None:
        self._agent_importers: list[AgentImporter] = []
        self._skill_importers: list[SkillImporter] = []

    def register_agent_importer(self, importer: AgentImporter) -> None:
        self._agent_importers.append(importer)

    def register_skill_importer(self, importer: SkillImporter) -> None:
        self._skill_importers.append(importer)

    def agent_formats(self) -> list[str]:
        return [i.format for i in self._agent_importers]

    def skill_formats(self) -> list[str]:
        return [i.format for i in self._skill_importers]

    def import_agent(
        self, source: dict[str, Any] | str, *, import_format: str | None = None
    ) -> AgentIdentity | None:
        """First matching importer wins; None if nothing matches or parse fails."""
        for importer in self._agent_importers:
            if import_format is not None:
                if importer.format != import_format:
                    continue
            elif not _safe_detect(importer, source):
                continue
            try:
                return importer.to_agent_config(source)
            except ValueError as exc:
                logger.warning("Agent import via '%s' failed: %s", importer.format, exc)
                return None
        return None

    def import_skills(
        self, source: dict[str, Any] | str, *, import_format: str | None = None
    ) -> list[SkillDefinition]:
        """First matching importer wins; [] if nothing matches or parse fails."""
        for importer in self._skill_importers:
            if import_format is not None:
                if importer.format != import_format:
                    continue
            elif not _safe_detect(importer, source):
                continue
            return importer.to_skill_definitions(source)
        return []


def _safe_detect(importer: AgentImporter | SkillImporter, source: dict[str, Any] | str) -> bool:
    try:
        return importer.detect(source)
    except Exception:
        logger.warning("Importer '%s' detect() raised; skipping", importer.format)
        return False


def default_importer_registry() -> ImporterRegistry:
    """Registry with the built-in importers, in canonical detection order."""
    from maistro.agents.importers.pi import PiAgentImporter
    from maistro.skills.importers.claude_code import ClaudeCodeSkillImporter

    registry = ImporterRegistry()
    registry.register_agent_importer(PiAgentImporter())
    registry.register_skill_importer(ClaudeCodeSkillImporter())
    return registry
