"""AgentImporter protocol + ImporterRegistry (SPEC-208).

The spec's ``to_agent_config()`` targets maistro's internal per-agent spec
type. That type is ``maistro.types.agent.AgentIdentity`` — the name
``maistro.types.AgentConfig`` denotes the *root configuration* object, not an
agent definition, so importers return ``AgentIdentity`` (deliberate deviation
from the spec's type name; the method name is kept).

M1-A convergence keeps that compatibility surface while exposing a pure
projection into canonical ``NodeTemplate``. The projection stays an adapter,
not a second importer API, until a production consumer is ready to use it.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro.graph.definitions import NodeTemplate
    from maistro.skills.importers.base import SkillImporter
    from maistro.types.agent import AgentIdentity
    from maistro.types.skill import SkillDefinition

from maistro.graph.import_provenance import SOURCE_IMPORT_PROVENANCE, import_provenance

logger = logging.getLogger("maistro.agents.importers")

LEGACY_DEFINITION_SNAPSHOT = "legacy_definition_snapshot"


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


def _reusable_snapshot(identity: AgentIdentity) -> dict[str, Any]:
    """Return JSON-shaped reusable behavior/config, excluding authority/state.

    This projection is intentionally explicit rather than derived from dataclass
    fields. A future trust, review, activation, or other authority field must
    not enter canonical reusable-definition metadata merely because it was
    added to ``AgentIdentity``.
    """
    reflected_phases = asdict(identity)["phases"]
    return {
        "name": identity.name,
        "version": identity.version,
        "description": identity.description,
        "soul_prompt_name": identity.soul_prompt_name,
        "model": identity.model,
        "model_fallbacks": list(identity.model_fallbacks),
        "model_constraints": dict(identity.model_constraints),
        "tools": list(identity.tools),
        "skills": list(identity.skills),
        "rules": list(identity.rules),
        "max_tool_rounds": identity.max_tool_rounds,
        "delegation_mode": identity.delegation_mode,
        "sub_agents": list(identity.sub_agents),
        "reasoning_strategy": identity.reasoning_strategy,
        "memory_config": dict(identity.memory_config),
        "phases": [dict(phase) for phase in reflected_phases],
    }


def _source_format(identity: AgentIdentity) -> str:
    provenance = identity.provenance.strip()
    if provenance.startswith("import:") and len(provenance) > len("import:"):
        return provenance.removeprefix("import:")
    return "legacy_agent_identity"


def agent_identity_to_node_template(
    identity: AgentIdentity,
    *,
    workspace_id: str,
    node_type: str,
    parameters: dict[str, Any] | None = None,
) -> NodeTemplate:
    """Project one legacy AgentIdentity into a canonical Workspace NodeTemplate.

    ``node_type`` is explicit because an import format does not prove which
    executable MAIstro node implements it. Source configuration is retained as
    inert migration/audit metadata. The projection grants no permissions,
    policies or Binding ids and excludes legacy trust/review/activation state.
    """
    from maistro.graph.definitions import NodeTemplate

    if not workspace_id.strip():
        raise ValueError("workspace_id must be a non-empty string")
    if not node_type.strip():
        raise ValueError("node_type must be a non-empty string")

    snapshot = _reusable_snapshot(identity)
    provenance = import_provenance(
        snapshot,
        source_format=_source_format(identity),
        source_definition="AgentIdentity",
        source_name=identity.name,
        source_version=identity.version,
    )
    return NodeTemplate(
        workspace_id=workspace_id,
        name=identity.name,
        node_type=node_type,
        parameters=dict(parameters or {}),
        binding_ids=[],
        permissions={},
        policies={},
        metadata={
            SOURCE_IMPORT_PROVENANCE: provenance,
            LEGACY_DEFINITION_SNAPSHOT: snapshot,
        },
    )


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
