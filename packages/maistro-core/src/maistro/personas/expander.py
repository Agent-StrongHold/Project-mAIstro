"""Persona expander — persona template → provisional agent roster (ADR-060 §2, SPEC-192 Stage 3).

Expands a persona template into one named :class:`AgentRecipe` per ``spawns:``
entry, all ``active: False`` pending the two-tier review gate, with
``hard_constraints`` wired as hard gates (criterion check specs resolved from
the persona's Tier 1 rubric — the payload Sentinel promotes to hard blocks).

Expansion is deterministic and idempotent: re-expanding the same template
produces identical records. ``AgentRecipe`` carries no activation flag, so the
governance state lives on :class:`ExpandedAgent` alongside the recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maistro.agents.recipes import AgentRecipe, RecipeRegistry
from maistro.agents.spec.agent_spec import AgentRole
from maistro.personas.schema import PersonaTemplate, SpawnSpec

# reasoning_strategy → recipe role. Personas spawn user-facing agents; both
# current strategies map onto the conversation runtime role.
_STRATEGY_ROLE: dict[str, AgentRole] = {
    "direct": AgentRole.CONVERSATION,
    "react": AgentRole.CONVERSATION,
}


@dataclass(frozen=True)
class HardGate:
    """One criterion promoted to a Sentinel hard block for one agent."""

    criterion: str
    check: dict[str, Any]  # vocabulary check-spec (Sentinel enforces this)


@dataclass(frozen=True)
class ExpandedAgent:
    """One spawned agent: recipe + eval bindings + governance state."""

    recipe: AgentRecipe
    active: bool  # always False at expansion; flipped by the review gate
    reasoning_strategy: str
    skills: list[str]
    scored_by: list[str]  # eval names from the persona that score this agent
    hard_gates: list[HardGate]
    inherits_voice: bool


@dataclass(frozen=True)
class ExpandedPersona:
    """Full expansion output: roster + shared soul prompt."""

    persona_id: str
    soul_prompt: str
    soul_prompt_name: str
    agents: list[ExpandedAgent] = field(default_factory=list)


def build_soul_prompt(template: PersonaTemplate) -> str:
    """Deterministically synthesise the shared soul prompt from voice.rules + voice.example."""
    voice = template.voice
    lines: list[str] = []
    if voice.archetype:
        lines.append(f"You are {voice.archetype}.")
    if voice.audience:
        lines.append(f"Your audience: {voice.audience}.")
    if voice.tone:
        lines.append(f"Tone: {voice.tone}.")
    if voice.rules:
        lines.append("Voice rules:")
        lines.extend(f"- {rule}" for rule in voice.rules)
    if voice.example:
        lines.append("Example of your voice:")
        lines.append(voice.example)
    return "\n".join(lines)


def _resolve_hard_gates(template: PersonaTemplate, spawn: SpawnSpec) -> list[HardGate]:
    checks: dict[str, dict[str, Any]] = {
        c.name: dict(c.check) for ev in template.evals for c in ev.criteria
    }
    return [HardGate(criterion=name, check=checks[name]) for name in spawn.hard_gates]


def _expand_spawn(template: PersonaTemplate, spawn: SpawnSpec, prompt_name: str) -> ExpandedAgent:
    recipe = AgentRecipe(
        name=f"{template.id}.{spawn.agent}",
        role=_STRATEGY_ROLE.get(spawn.reasoning_strategy, AgentRole.CONVERSATION),
        description=spawn.role,
        prompt_name=prompt_name,
        tools=list(spawn.tools),
    )
    return ExpandedAgent(
        recipe=recipe,
        active=False,
        reasoning_strategy=spawn.reasoning_strategy,
        skills=list(spawn.skills),
        scored_by=list(spawn.scored_by),
        hard_gates=_resolve_hard_gates(template, spawn),
        inherits_voice=spawn.inherits_voice,
    )


def expand_persona(
    template: PersonaTemplate,
    registry: RecipeRegistry | None = None,
) -> ExpandedPersona:
    """Expand a persona template into named AgentRecipe records (all inactive).

    When ``registry`` is given, each recipe is registered (in-memory) so the
    existing spawner/factory runtime (ADR-006) can resolve it by name.
    """
    if template.kind == "department":
        return ExpandedPersona(
            persona_id=template.id,
            soul_prompt="",
            soul_prompt_name="",
            agents=[],
        )

    prompt_name = f"{template.id}_voice"
    agents = [_expand_spawn(template, spawn, prompt_name) for spawn in template.spawns]

    if registry is not None:
        for agent in agents:
            registry.register(agent.recipe)

    return ExpandedPersona(
        persona_id=template.id,
        soul_prompt=build_soul_prompt(template),
        soul_prompt_name=prompt_name,
        agents=agents,
    )
