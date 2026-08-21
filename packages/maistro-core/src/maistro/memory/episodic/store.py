"""In-memory episodic store (ADR-016)."""

from __future__ import annotations

from datetime import UTC, datetime

from maistro.memory.episodic.tiers import clamp_weight
from maistro.memory.episodic.tiers import reinforce as _reinforce
from maistro.memory.episodic.tiers import tick_decay as _tick_decay
from maistro.memory.scopes import build_scope_filter, matches_scope
from maistro.memory.types import DecaySweep, EpisodicMemory


class InMemoryEpisodicStore:
    def __init__(self) -> None:
        self._memories: list[EpisodicMemory] = []

    async def store(self, memory: EpisodicMemory) -> str:
        self._memories.append(memory)
        return memory.memory_id

    async def retrieve(
        self,
        query: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        scope_filters = build_scope_filter(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
        )
        query_words = set(query.lower().split())
        scored: list[tuple[float, EpisodicMemory]] = []

        for mem in self._memories:
            if mem.deleted:
                continue
            if not matches_scope(mem, scope_filters):
                continue
            mem_words = set(mem.content.lower().split())
            overlap = len(mem_words & query_words)
            if overlap > 0:
                scored.append((overlap * mem.weight, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in scored[:limit]]

    async def reinforce(self, memory_id: str, delta: float = 0.05) -> None:
        for i, mem in enumerate(self._memories):
            if mem.memory_id == memory_id:
                self._memories[i] = _reinforce(mem, delta)
                break

    async def apply_decay(self, *, now: datetime | None = None) -> DecaySweep:
        """Decay every live memory once (SPEC-080126-9e42).

        Entries already resting on their tier floor are still swept — the tick
        refreshes their timestamp — but they are reported as ``at_floor`` rather
        than ``decayed`` because their weight cannot move. That is the
        wisdom/regret floor promise being exercised, not a no-op.
        """
        now = now or datetime.now(UTC)
        sweep = DecaySweep()
        for i, mem in enumerate(self._memories):
            if mem.deleted:
                continue
            floor = clamp_weight(mem.tier, float("-inf"))
            decayed = _tick_decay(mem, now=now)
            self._memories[i] = decayed
            sweep = DecaySweep(
                scanned=sweep.scanned + 1,
                decayed=sweep.decayed + (1 if decayed.weight != mem.weight else 0),
                at_floor=sweep.at_floor + (1 if decayed.weight <= floor else 0),
            )
        return sweep

    async def list_by_scope(
        self,
        *,
        agent_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        project_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 50,
    ) -> list[EpisodicMemory]:
        scope_filters = build_scope_filter(
            agent_id=agent_id,
            team_id=team_id,
            org_id=org_id,
        )
        # No agent/team/org filter given: project_id alone selects memories
        # (e.g. project changelog recall), independent of scope hierarchy.
        no_scope_filter = not (agent_id or team_id or org_id)
        matched = [
            mem
            for mem in self._memories
            if not mem.deleted
            and (no_scope_filter or matches_scope(mem, scope_filters))
            and mem.weight >= min_weight
            and (not project_id or mem.project_id == project_id)
        ]
        matched.sort(key=lambda m: m.weight, reverse=True)
        return matched[:limit]
