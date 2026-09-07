"""In-memory episodic store (ADR-016)."""

from __future__ import annotations

from datetime import UTC, datetime

from maistro.memory.episodic.ranking import rank
from maistro.memory.episodic.tiers import clamp_weight
from maistro.memory.episodic.tiers import reinforce as _reinforce
from maistro.memory.episodic.tiers import tick_decay as _tick_decay
from maistro.memory.scopes import build_scope_filter, matches_scope
from maistro.memory.types import REINFORCE_DELTA, DecaySweep, EpisodicMemory
from maistro.observability.correlation import observed_provenance


def _selected(
    memory: EpisodicMemory,
    *,
    scope_filters: list[tuple[str, str | None]],
    no_scope_filter: bool,
    min_weight: float,
    project_id: str | None,
) -> bool:
    """Whether `list_by_scope` returns this memory.

    A named predicate rather than four clauses inside the comprehension: the
    scope axes gained `user_id` (#622) and the conditions carried the method
    past the complexity ceiling, which is the linter noticing that "select"
    had become a rule worth naming.
    """
    if memory.deleted:
        return False
    if not no_scope_filter and not matches_scope(memory, scope_filters):
        return False
    if memory.weight < min_weight:
        return False
    return not project_id or memory.project_id == project_id


class InMemoryEpisodicStore:
    """Episodic memory in this process's heap, for the lifetime of this process.

    Stated because it was not, and the absence cost something: until #710 the
    container wired this store whatever `database_url` said, so every tier,
    weight and reinforcement count in ADR-080 was lost at every restart and
    differed between replicas. The durable stores are
    `maistro.persistence.pg_episodic` and `maistro.persistence.sqlite_episodic`;
    this one is what a `memory://` deployment gets, deliberately.
    """

    def __init__(self) -> None:
        self._memories: list[EpisodicMemory] = []

    async def store(self, memory: EpisodicMemory) -> str:
        """Store a memory, naming the execution that produced it.

        The volatile store fills provenance too, for the reason
        `InMemoryLearningStore.store` states: it is the default backend in dev
        and test, so a store that skipped this would let every behavioural
        test pass while only the durable ones did the work. Assigned onto the
        object because this store keeps the caller's instance (#64).
        """
        provenance = observed_provenance(
            run_id=memory.run_id,
            node_run_id=memory.node_run_id,
            attempt_id=memory.attempt_id,
        )
        memory.run_id = provenance.run_id
        memory.node_run_id = provenance.node_run_id
        memory.attempt_id = provenance.attempt_id
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
        scoped = [m for m in self._memories if not m.deleted and matches_scope(m, scope_filters)]
        # One formula, in ranking.py. This used to score `overlap_count *
        # weight` -- a fourth spelling of ADR-080 part D that ranked
        # differently from the other three (#622).
        return rank(query, scoped, k=limit)

    async def reinforce(self, memory_id: str, delta: float = REINFORCE_DELTA) -> None:
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
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        project_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 50,
    ) -> list[EpisodicMemory]:
        scope_filters = build_scope_filter(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
        )
        # No agent/user/team/org filter given: project_id alone selects memories
        # (e.g. project changelog recall), independent of scope hierarchy.
        no_scope_filter = not (agent_id or user_id or team_id or org_id)
        matched = [
            mem
            for mem in self._memories
            if _selected(
                mem,
                scope_filters=scope_filters,
                no_scope_filter=no_scope_filter,
                min_weight=min_weight,
                project_id=project_id,
            )
        ]
        # `memory_id` breaks the tie, because `limit` cuts through equal
        # weights constantly -- every new memory defaults to 0.3. A stable sort
        # on weight alone returns insertion order, which no durable store can
        # reproduce, so the three stores would answer differently and, past the
        # limit, with different memories (Codex, #710).
        matched.sort(key=lambda m: (-m.weight, m.memory_id))
        return matched[:limit]

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[EpisodicMemory]:
        """The memories this Run stored, newest first.

        The same contract as `LearningStore.produced_by` (#709): an empty
        `run_id` returns nothing rather than every unattributed memory, and the
        read is org-scoped so a Run's name never widens what a caller can see
        (#64).
        """
        if not run_id:
            return []
        return [
            m for m in self._memories if m.run_id == run_id and m.org_id == org_id and not m.deleted
        ][::-1]
