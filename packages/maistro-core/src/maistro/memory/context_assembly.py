"""Default ContextAssemblyPolicy: Layer 0-4 memory assembly (ADR-091 / SPEC-244).

Three things ADR-091 decides that the first implementation did not do (#622):

* **"Always include (weight >= 0.6) ... regardless of token budget."**
  `ALWAYS_INCLUDE_WEIGHT` was defined and never read. Every memory went into one
  string and the string was sliced, so a REGRET could be dropped, or halved, by
  a budget it is explicitly exempt from.
* **"Layers 1-3 are truncated in reverse priority (layer 3 first)."**
  Layer 3 was assembled first against the full remaining budget and layer 1 got
  what was left, which is that rule backwards: the project changelog outranked
  the agent's own task context.
* **Ranking.** Layer 1 was `list_by_scope` at a weight floor — every scoped
  memory, in store order, with no notion of what the run is about. Which ones
  survived the budget was an accident of insertion order.

The budget now drops whole memories in rank order and never emits a fragment. A
half-sentence of a memory is not a smaller memory; it is a sentence the model
did not write and cannot check, spending budget to mislead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.memory.episodic.retrieval import ScoredEpisodicRetrieval

if TYPE_CHECKING:
    from maistro.projects.store import ProjectStore
    from maistro.protocols.embeddings import EmbeddingClient
    from maistro.protocols.memory import EpisodicStore, OutcomeStore
    from maistro.types.memory import EpisodicMemory

# ADR-091 weight bands. These are invariants of the ADR, not configuration.
ALWAYS_INCLUDE_WEIGHT = 0.6
BUDGET_INCLUDE_WEIGHT = 0.3
WISDOM_WEIGHT = 0.9

_CHARS_PER_TOKEN = 4

#: How many scoped memories Layer 1 recalls before the budget packs them.
#: The band filter and the budget both cut further; this only bounds the work.
_LAYER1_LIMIT = 50


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def _pack(memories: list[EpisodicMemory], budget_tokens: int | None) -> tuple[str, int]:
    """Whole memories, in the order given, until the budget is spent.

    `None` means unbounded — a caller that named no budget is not a caller with
    a budget of zero, and reading it as zero would silently drop everything
    below the always-include band.

    Returns the text and the tokens it cost. A memory at or above
    `ALWAYS_INCLUDE_WEIGHT` is taken whatever the budget says and can overspend
    it — ADR-091 calls these "the memories the system must not forget", and a
    band that yields to the budget is not a band. Everything below it is taken
    only while it fits *whole*: a memory that would not fit is skipped, and a
    later, smaller one may still be taken, because the alternative is leaving
    budget unspent to preserve an ordering the reader cannot see anyway.
    """
    kept: list[str] = []
    spent = 0
    for memory in memories:
        cost = _estimate_tokens(memory.content)
        if (
            memory.weight >= ALWAYS_INCLUDE_WEIGHT
            or budget_tokens is None
            or spent + cost <= budget_tokens
        ):
            kept.append(memory.content)
            spent += cost
    return "\n".join(kept), spent


class DefaultContextAssemblyPolicy:
    """Default Layer 0-4 implementation wired to existing memory stores."""

    def __init__(
        self,
        *,
        episodic_store: EpisodicStore,
        outcome_store: OutcomeStore,
        project_store: ProjectStore,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.episodic_store = episodic_store
        self.outcome_store = outcome_store
        self.project_store = project_store
        self._retrieval = ScoredEpisodicRetrieval(episodic_store, embedding_client)

    async def layer0(self, project_id: str) -> str:
        project = await self.project_store.get(project_id)
        return project.profile_markdown if project else ""

    async def layer1(
        self,
        run_id: str,
        agent_id: str,
        session_id: str,
        query: str = "",
        budget_tokens: int | None = None,
    ) -> str:
        """Active task context, ranked against what this run is about.

        `query` and `budget_tokens` are what makes the ADR's own rule
        expressible: without a query there is no relevance to rank by, and
        without the budget here the packing would happen in `assemble`, on a
        joined string, where a whole memory is no longer a unit (#622).

        An empty query means the caller has nothing to rank by. That is not a
        reason to send nothing: the weight bands still apply, so the answer is
        the scoped set in weight order — which is what the store returns.
        """
        if query:
            memories = await self._retrieval.retrieve(
                query,
                agent_id=agent_id,
                min_weight=BUDGET_INCLUDE_WEIGHT,
                limit=_LAYER1_LIMIT,
            )
        else:
            memories = await self.episodic_store.list_by_scope(
                agent_id=agent_id, min_weight=BUDGET_INCLUDE_WEIGHT, limit=_LAYER1_LIMIT
            )
        text, _spent = _pack(memories, budget_tokens)
        return text

    async def layer2(self, session_id: str, budget_tokens: int) -> str:
        return ""

    async def layer3(self, project_id: str, n: int = 20, budget_tokens: int | None = None) -> str:
        experience = await self.outcome_store.get_experience_context(
            task_type="", limit=n, project_id=project_id
        )
        wisdom_memories = await self.episodic_store.list_by_scope(
            project_id=project_id, min_weight=WISDOM_WEIGHT, limit=n
        )
        remaining = budget_tokens
        parts: list[str] = []
        # The experience text is one unit, not a list, so it is included whole
        # or not at all for the same reason a memory is.
        if experience and (remaining is None or _estimate_tokens(experience) <= remaining):
            parts.append(experience)
            if remaining is not None:
                remaining -= _estimate_tokens(experience)
        memories_text, _spent = _pack(wisdom_memories, remaining)
        if memories_text:
            parts.append(memories_text)
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
        query: str = "",
    ) -> str:
        """Layers 0-4 in order, spending the budget in ADR-091's priority.

        Layer 0 is never truncated and is charged against the budget first.
        Then layers 1, 2, 3, 4 in that order — the ADR's "truncated in reverse
        priority (layer 3 first)" read forwards: whoever asks first is the last
        to lose content.
        """
        layer0_text = await self.layer0(project_id)
        remaining = max(budget_tokens - _estimate_tokens(layer0_text), 0)

        layer1_text = await self.layer1(run_id, agent_id, session_id, query, remaining)
        remaining = max(remaining - _estimate_tokens(layer1_text), 0)

        layer2_text = await self.layer2(session_id, remaining)
        remaining = max(remaining - _estimate_tokens(layer2_text), 0)

        layer3_text = await self.layer3(project_id, budget_tokens=remaining)
        remaining = max(remaining - _estimate_tokens(layer3_text), 0)

        layer4_text = await self.layer4(project_id)

        return "\n\n".join(
            t for t in (layer0_text, layer1_text, layer2_text, layer3_text, layer4_text) if t
        )
