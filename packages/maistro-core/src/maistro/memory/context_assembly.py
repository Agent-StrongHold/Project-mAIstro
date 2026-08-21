"""Default ContextAssemblyPolicy: Layer 0-4 memory assembly (ADR-091 / SPEC-244)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.projects.store import ProjectStore
    from maistro.protocols.memory import EpisodicStore, OutcomeStore

# ADR-091 weight bands.
ALWAYS_INCLUDE_WEIGHT = 0.6
BUDGET_INCLUDE_WEIGHT = 0.3
WISDOM_WEIGHT = 0.9


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


class DefaultContextAssemblyPolicy:
    """Default Layer 0-4 implementation wired to existing memory stores."""

    def __init__(
        self,
        *,
        episodic_store: EpisodicStore,
        outcome_store: OutcomeStore,
        project_store: ProjectStore,
    ) -> None:
        self.episodic_store = episodic_store
        self.outcome_store = outcome_store
        self.project_store = project_store

    async def layer0(self, project_id: str) -> str:
        project = await self.project_store.get(project_id)
        return project.profile_markdown if project else ""

    async def layer1(self, run_id: str, agent_id: str, session_id: str) -> str:
        memories = await self.episodic_store.list_by_scope(
            agent_id=agent_id, min_weight=BUDGET_INCLUDE_WEIGHT
        )
        return "\n".join(m.content for m in memories)

    async def layer2(self, session_id: str, budget_tokens: int) -> str:
        return ""

    async def layer3(self, project_id: str, n: int = 20) -> str:
        experience = await self.outcome_store.get_experience_context(
            task_type="", limit=n, project_id=project_id
        )
        wisdom_memories = await self.episodic_store.list_by_scope(
            project_id=project_id, min_weight=WISDOM_WEIGHT, limit=n
        )
        parts = [experience] if experience else []
        parts.extend(m.content for m in wisdom_memories)
        return "\n".join(parts)

    async def layer4(self, project_id: str) -> str:
        return ""

    async def assemble(
        self,
        project_id: str,
        run_id: str,
        agent_id: str,
        session_id: str,
        budget_tokens: int,
    ) -> str:
        layer0_text = await self.layer0(project_id)
        remaining = max(budget_tokens - _estimate_tokens(layer0_text), 0)

        layer3_text = await self.layer3(project_id)
        layer3_text = layer3_text[: remaining * 4]
        remaining = max(remaining - _estimate_tokens(layer3_text), 0)

        layer2_text = await self.layer2(session_id, remaining)
        layer2_text = layer2_text[: remaining * 4]
        remaining = max(remaining - _estimate_tokens(layer2_text), 0)

        layer1_text = await self.layer1(run_id, agent_id, session_id)
        layer1_text = layer1_text[: remaining * 4]
        remaining = max(remaining - _estimate_tokens(layer1_text), 0)

        layer4_text = await self.layer4(project_id)
        layer4_text = layer4_text[: remaining * 4]

        return "\n\n".join(
            t for t in (layer0_text, layer1_text, layer2_text, layer3_text, layer4_text) if t
        )
