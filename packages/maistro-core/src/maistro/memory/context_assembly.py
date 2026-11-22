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

import logging
import time
from typing import TYPE_CHECKING

from maistro.memory.episodic.retrieval import ScoredEpisodicRetrieval

if TYPE_CHECKING:
    from maistro.memory.working.manager import WorkingMemoryManager
    from maistro.memory.working.protocol import EntityContext
    from maistro.projects.scope_store import ProjectScopeStore
    from maistro.protocols.embeddings import EmbeddingClient
    from maistro.protocols.memory import EpisodicStore, OutcomeStore
    from maistro.types.memory import EpisodicMemory

logger = logging.getLogger(__name__)

# ADR-091 weight bands. These are invariants of the ADR, not configuration.
ALWAYS_INCLUDE_WEIGHT = 0.6
BUDGET_INCLUDE_WEIGHT = 0.3
WISDOM_WEIGHT = 0.9

_CHARS_PER_TOKEN = 4

#: How many scoped memories Layer 1 recalls before the budget packs them.
#: The band filter and the budget both cut further; this only bounds the work.
_LAYER1_LIMIT = 50

#: Per-entity content snippet cap in the Layer 4 rendering.
_LAYER4_SNIPPET_CHARS = 160

#: Minimum spacing between corruption-heal rebuild attempts per policy. A
#: recall that fails deterministically must not turn every retrieval into a
#: full discard-and-reindex; one rebuild per interval bounds that cost while
#: still recovering a genuinely corrupted projection on the next call.
_WORKING_REBUILD_MIN_INTERVAL_S = 60.0


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


def _render_graph_context(context: list[EntityContext]) -> str:
    """Render entity graph context as bounded, deterministic text.

    Layer 4 has no budget parameter in the protocol, so the renderer bounds
    itself: eight entities, five relations and three citing memories each,
    with content snippets capped. Every line names the entity it came from,
    so a model reading the layer can tell graph structure from memory text.
    """
    if not context:
        return ""
    lines: list[str] = []
    for entry in context:
        label = entry.entity.label or entry.entity.name
        lines.append(f"entity: {label} ({entry.entity.mention_count} memories)")
        if entry.relations:
            related = ", ".join(
                f"{relation.target} ({relation.weight:.0f})" for relation in entry.relations
            )
            lines.append(f"  associated with: {related}")
        for memory in entry.memories:
            snippet = memory.content.strip().replace("\n", " ")
            if len(snippet) > _LAYER4_SNIPPET_CHARS:
                snippet = snippet[:_LAYER4_SNIPPET_CHARS] + "..."
            provenance = f"run {memory.run_id}" if memory.run_id else "unattributed"
            lines.append(
                f"  mentioned in: {snippet} [{memory.tier.value} w={memory.weight:.2f}, {provenance}]"
            )
    return "\n".join(lines)


class DefaultContextAssemblyPolicy:
    """Default Layer 0-4 implementation wired to existing memory stores."""

    def __init__(
        self,
        *,
        episodic_store: EpisodicStore,
        outcome_store: OutcomeStore,
        project_store: ProjectScopeStore,
        embedding_client: EmbeddingClient | None = None,
        working_memory: WorkingMemoryManager | None = None,
    ) -> None:
        self.episodic_store = episodic_store
        self.outcome_store = outcome_store
        self.project_store = project_store
        # The per-Workspace hot projection (ADR-082226-5104 §5), when the
        # container wired one. Absent, every layer below answers exactly as
        # it did before: the durable stores remain the fallback and the truth.
        self.working_memory = working_memory
        self._retrieval = ScoredEpisodicRetrieval(episodic_store, embedding_client)
        self._embedding_client = embedding_client
        # Monotonic timestamp of the last corruption-heal rebuild attempt, or
        # None while the policy has not needed one (see _rebuild_after_failure).
        self._working_rebuild_at: float | None = None

    async def layer0(self, project_id: str) -> str:
        project = await self.project_store.get(project_id)
        if project is None:
            return ""
        # Canonical Projects keep creation/context metadata in `metadata`; the
        # legacy attribute remains readable for standalone policy callers.
        profile = getattr(project, "profile_markdown", None)
        if isinstance(profile, str):
            return profile
        metadata = getattr(project, "metadata", {})
        value = metadata.get("profile_markdown", "")
        return value if isinstance(value, str) else ""

    async def layer1(
        self,
        run_id: str,
        agent_id: str,
        session_id: str,
        query: str = "",
        budget_tokens: int | None = None,
        *,
        project_id: str = "",
    ) -> str:
        """Active task context, ranked against what this run is about.

        `query` and `budget_tokens` are what makes the ADR's own rule
        expressible: without a query there is no relevance to rank by, and
        without the budget here the packing would happen in `assemble`, on a
        joined string, where a whole memory is no longer a unit (#622).

        An empty query means the caller has nothing to rank by. That is not a
        reason to send nothing: the weight bands still apply, so the answer is
        the scoped set in weight order — which is what the store returns.

        A nonempty `project_id` keeps only memories attributed to that
        Project: an agent id reused across Workspaces must not recall one
        Workspace's memories in another (#1047). A memory with no project is
        not guessed into one, which includes an unattributed GLOBAL memory: a
        Project run sees only what was recorded for that Project. Only an empty
        string means no project filter; whitespace remains an exact value.

        With a working-memory projection wired and healthy, Layer 1 is the
        indexed hot path (ADR-082226-5104 §5): BM25 over the projection's
        inverted index plus similarity against embeddings stored at write
        time — no per-read re-embedding of candidates, no whole-corpus scan.
        The projection applies the same scope predicate and the same weight
        floor, so the hot path can rank faster, never see wider. Any failure
        to hydrate degrades to the durable path below, loudly logged by the
        manager rather than silently skipped.
        """
        memories = await self._hot_recall(
            query,
            agent_id=agent_id,
            project_id=project_id,
            min_weight=BUDGET_INCLUDE_WEIGHT,
            limit=_LAYER1_LIMIT,
        )
        if memories is None:
            if query:
                memories = await self._retrieval.retrieve(
                    query,
                    agent_id=agent_id,
                    project_id=project_id,
                    min_weight=BUDGET_INCLUDE_WEIGHT,
                    limit=_LAYER1_LIMIT,
                )
            else:
                memories = await self.episodic_store.list_by_scope(
                    agent_id=agent_id,
                    project_id=project_id,
                    min_weight=BUDGET_INCLUDE_WEIGHT,
                    limit=_LAYER1_LIMIT,
                )
        text, _spent = _pack(memories, budget_tokens)
        return text

    async def _hot_recall(
        self,
        query: str,
        *,
        agent_id: str,
        project_id: str,
        min_weight: float,
        limit: int,
    ) -> list[EpisodicMemory] | None:
        """Layer 1 through the working projection, or None to use the stores.

        None is returned — not [] — when there is no healthy projection:
        an empty hot result and "no hot path" are different answers, and only
        the second may fall back.
        """
        if self.working_memory is None:
            return None
        if not query.strip():
            # No query: nothing to rank by on the hot path either. The
            # store's weight-ordered scoped set is the answer, as before.
            return None
        if not await self.working_memory.ensure_hydrated():
            logger.warning(
                "working-memory[%s]: hot path unavailable (%s); using durable retrieval",
                self.working_memory.workspace_id,
                self.working_memory.degraded_reason() or "no recorded reason",
            )
            return None
        projection = self.working_memory.projection()
        try:
            scored = await projection.recall(
                query,
                agent_id=agent_id,
                project_id=project_id,
                min_weight=min_weight,
                limit=limit,
            )
        except Exception:
            logger.exception(
                "working-memory[%s]: hot recall failed; degrading to durable retrieval",
                self.working_memory.workspace_id,
            )
            await self._rebuild_after_failure()
            return None
        return [hit.memory for hit in scored]

    async def _rebuild_after_failure(self) -> None:
        """The ADR-082226-5104 §6 corruption path, wired to its trigger.

        A projection that constructs fine but fails mid-read is the one
        corruption signal this implementation can observe (a torn index, a
        backend that died between construction and query). The ADR's answer —
        "if a projection is corrupted, throw it away and rebuild it" — is
        exactly :meth:`WorkingMemoryManager.rebuild`: discard the derived
        state, rehydrate from authoritative PostgreSQL truth, touch nothing
        durable. The current read is answered from the durable path either
        way; the rebuild is for the *next* caller. Throttled so a
        deterministically failing recall cannot turn every retrieval into a
        full re-index.
        """
        assert self.working_memory is not None
        now = time.monotonic()
        if (
            self._working_rebuild_at is not None
            and now - self._working_rebuild_at < _WORKING_REBUILD_MIN_INTERVAL_S
        ):
            return
        self._working_rebuild_at = now
        try:
            await self.working_memory.rebuild()
        except Exception:
            logger.exception(
                "working-memory[%s]: corruption-heal rebuild failed (%s); staying on the "
                "durable path",
                self.working_memory.workspace_id,
                self.working_memory.degraded_reason() or "no recorded reason",
            )

    async def layer2(self, session_id: str, budget_tokens: int) -> str:
        return ""

    async def layer3(
        self,
        project_id: str,
        n: int = 20,
        budget_tokens: int | None = None,
        org_id: str = "",
    ) -> str:
        # Outcome text is a scoped prompt input. Callers that have no resolved
        # org/project must not turn this into a global read.
        experience = ""
        if org_id and project_id:
            experience = await self.outcome_store.get_experience_context(
                task_type="", limit=n, org_id=org_id, project_id=project_id
            )
        wisdom_memories = await self.episodic_store.list_by_scope(
            project_id=project_id, min_weight=WISDOM_WEIGHT, limit=n
        )
        if org_id:
            # Keep project-only non-global history, then add the caller's
            # authorized GLOBAL wisdom through the same store scope rule.
            # Passing org_id to the first read alone would drop its AGENT,
            # USER and TEAM changelog rows. Both bounded reads retain the
            # existing protocol and scope authority; union before ranking.
            scoped_memories = await self.episodic_store.list_by_scope(
                org_id=org_id, project_id=project_id, min_weight=WISDOM_WEIGHT, limit=n
            )
            unique = {memory.memory_id: memory for memory in wisdom_memories + scoped_memories}
            wisdom_memories = sorted(
                unique.values(), key=lambda memory: (-memory.weight, memory.memory_id)
            )[:n]
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
        """Knowledge-graph context from the Workspace's working projection.

        ADR-091 deferred this layer; ADR-082226-5104 §8 answers it: Layer 4 is
        the working projection's entity graph — the entities this Workspace's
        memories mention, the associations between them, and the memories that
        cite them. The text is rendered from
        :meth:`WorkspaceWorkingMemoryProjection.entity_context`, so it is real
        graph context for a populated Workspace.

        An absent, unhealthy, or empty projection returns ``""`` — the honest
        answer for "no knowledge-graph context is being served", which is
        still the truth for a deployment with no working memory wired or a
        Workspace whose projection is empty or degraded.
        """
        if self.working_memory is None:
            return ""
        if not await self.working_memory.ensure_hydrated():
            logger.warning(
                "working-memory[%s]: layer4 graph context unavailable (%s)",
                self.working_memory.workspace_id,
                self.working_memory.degraded_reason() or "no recorded reason",
            )
            return ""
        projection = self.working_memory.projection()
        try:
            context = await projection.entity_context(project_id=project_id or None)
        except Exception:
            logger.exception(
                "working-memory[%s]: layer4 graph context failed; serving none",
                self.working_memory.workspace_id,
            )
            await self._rebuild_after_failure()
            return ""
        return _render_graph_context(context)

    async def assemble(
        self,
        project_id: str,
        run_id: str,
        agent_id: str,
        session_id: str,
        budget_tokens: int,
        query: str = "",
        org_id: str = "",
    ) -> str:
        """Layers 0-4 in order, spending the budget in ADR-091's priority.

        Layer 0 is never truncated and is charged against the budget first.
        Then layers 1, 2, 3, 4 in that order — the ADR's "truncated in reverse
        priority (layer 3 first)" read forwards: whoever asks first is the last
        to lose content.
        """
        layer0_text = await self.layer0(project_id)
        remaining = max(budget_tokens - _estimate_tokens(layer0_text), 0)

        layer1_text = await self.layer1(
            run_id, agent_id, session_id, query, remaining, project_id=project_id
        )
        remaining = max(remaining - _estimate_tokens(layer1_text), 0)

        layer2_text = await self.layer2(session_id, remaining)
        remaining = max(remaining - _estimate_tokens(layer2_text), 0)

        # Layer 3 also carries project-scoped episodic wisdom. Keep that
        # non-Outcome portion available without an org, while layer3 itself
        # refuses the unscoped Outcome read.
        layer3_text = await self.layer3(project_id, budget_tokens=remaining, org_id=org_id)
        remaining = max(remaining - _estimate_tokens(layer3_text), 0)

        layer4_text = await self.layer4(project_id)

        return "\n\n".join(
            t for t in (layer0_text, layer1_text, layer2_text, layer3_text, layer4_text) if t
        )
