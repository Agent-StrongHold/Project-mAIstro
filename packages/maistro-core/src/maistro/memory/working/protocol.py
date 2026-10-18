"""WorkingMemory protocol and record types (ADR-082226-5104 §5-6).

The protocol is MAIstro-owned. A LadybugDB-backed adapter (or any other hot
backend) implements this; nothing above the protocol may know which engine
holds the working graph. The invariants the protocol carries:

* **Disposable.** ``reset``/``evict`` exist because a projection is discarded,
  not because its contents matter. Rebuilding from the authoritative
  :class:`~maistro.types.memory.EpisodicStore` must reproduce everything the
  durable store can prove and nothing it cannot.
* **Isolated.** One working graph per active Workspace. Implementations are
  constructed per workspace id; there is no operation that addresses two
  workspaces at once, so cross-Workspace traversal is structurally impossible
  rather than merely forbidden.
* **Scope-preserving.** Recall takes the same scope axes the durable stores
  take and answers with the same :func:`~maistro.memory.scopes.matches_scope`
  predicate — a hot index can rank faster, never see wider.
* **Explicitly degraded.** Every implementation reports
  :attr:`WorkingMemoryStats.vector_ready` and a ``degraded_reason``, so a
  caller never claims graph or vector recall is active when it is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.types.memory import EpisodicMemory

if TYPE_CHECKING:
    from datetime import datetime

#: Identity of the embedding model that produced the stored vectors.
#:
#: The working projection is disposable, so its embedding dimensionality/model
#: may differ from durable pgvector's — but the choice must be explicit, and a
#: projection built under one model must never silently answer similarity
#: questions under another. A projection whose stored model identity does not
#: match the manager's configured identity drops its vectors and re-embeds
#: (or degrades to lexical-only, loudly) instead of mixing.
DEFAULT_EMBEDDING_MODEL = ""


@dataclass(frozen=True)
class EntityRecord:
    """A named entity in the working graph.

    ``name`` is the normalized (case-folded) form; ``label`` keeps the first
    surface form seen. ``mention_count`` counts distinct memories whose text
    or metadata names the entity, and ``memory_ids`` are exactly those
    memories — the ``Entity -> MentionedIn -> Memory`` edges, without a
    separate edge table.
    """

    name: str
    label: str
    mention_count: int
    memory_ids: tuple[str, ...]


@dataclass(frozen=True)
class RelationRecord:
    """A directed working-graph edge between two entities.

    ``kind`` is a relationship label (``"co_occurs_with"`` for the no-LLM
    path's co-occurrence edges; richer kinds may arrive through governed
    extraction later). ``weight`` is the observation count behind the edge —
    a temporary association, exactly the class of thing ADR-082226-5104 §6
    says working memory may hold that durable memory should not. Nothing here
    is durable truth until Dreaming promotes it through the canonical Run.
    """

    source: str
    target: str
    kind: str
    weight: float


@dataclass(frozen=True)
class ScoredWorkingMemory:
    """One recall hit: the authoritative record plus the hot-path scores."""

    memory: EpisodicMemory
    lexical_score: float
    vector_score: float

    @property
    def memory_id(self) -> str:
        return self.memory.memory_id


@dataclass(frozen=True)
class EntityContext:
    """Layer 4's unit: one entity, its strongest relations, its memories."""

    entity: EntityRecord
    relations: tuple[RelationRecord, ...]
    memories: tuple[EpisodicMemory, ...]


@dataclass(frozen=True)
class TraversalResult:
    """A bounded traversal from a start entity over working-graph edges."""

    visited: tuple[str, ...]
    edges: tuple[RelationRecord, ...]


@dataclass(frozen=True)
class HydrationReport:
    """What one hydrate pass did, so idempotence is observable, not assumed."""

    hydrated: int
    updated: int
    unchanged: int
    deleted: int

    @property
    def total(self) -> int:
        return self.hydrated + self.updated + self.unchanged + self.deleted


@dataclass(frozen=True)
class WorkingMemoryStats:
    """Observable state of one working projection.

    ``degraded_reason`` is the honesty field: empty when the projection is
    serving what it claims, and a human-readable reason when part of it is
    not — an embedding backend that failed, a model-identity mismatch, a
    rebuild in progress. A caller that cannot distinguish "no results" from
    "no working index" is a caller that will one day report hot recall as
    active while serving nothing.
    """

    records: int
    entities: int
    relations: int
    index_terms: int
    embedded_records: int
    embedding_model: str
    vector_ready: bool
    degraded_reason: str
    embedding_failures: int
    last_hydrated_at: datetime | None = None
    hydrated_total: int = 0
    updated_total: int = 0
    deleted_total: int = 0
    rebuilds: int = 0


@runtime_checkable
class WorkingMemory(Protocol):
    """The per-Workspace working-memory graph (ADR-082226-5104 §5-6).

    Minimum surface: hydrate/store/update/delete, lexical recall, vector
    recall, entity lookup and graph context, traversal, reset. Implementations
    must keep ``workspace_id`` immutable — it is the isolation boundary.
    """

    @property
    def workspace_id(self) -> str:
        """The Workspace this working graph belongs to. Never mutated."""
        ...

    @property
    def stats(self) -> WorkingMemoryStats:
        """Observable state, including an explicit ``degraded_reason``."""
        ...

    async def hydrate(self, memories: list[EpisodicMemory]) -> HydrationReport:
        """Materialise authoritative records into the working graph.

        Idempotent: re-hydrating the same durable state reports every record
        ``unchanged``. Records the authoritative store has since deleted are
        removed; records whose content or weight changed are updated in place
        (re-indexed, re-embedded).
        """
        ...

    async def store(self, memory: EpisodicMemory) -> None:
        """Index one new record (a memory stored durably while hot)."""
        ...

    async def update(
        self, memory_id: str, *, content: str | None = None, weight: float | None = None
    ) -> bool:
        """Update a record's content and/or weight.

        Content updates re-tokenise, re-index and re-embed before returning:
        a failed re-embed must drop the previous embedding rather than leave
        the index describing content that no longer exists. Returns False for
        an unknown memory_id.
        """
        ...

    async def delete(self, memory_id: str) -> bool:
        """Remove a record and every edge/index entry it owns. False if absent."""
        ...

    async def recall(
        self,
        query: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        project_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 10,
    ) -> list[ScoredWorkingMemory]:
        """Hybrid hot recall: indexed BM25 lexical term + stored-vector term.

        Scope axes mean exactly what :meth:`EpisodicStore.list_by_scope`'s
        mean, and the same predicate decides visibility. The query is embedded
        at most once; candidate embeddings were stored at write time and are
        never recomputed during a read.
        """
        ...

    async def recall_lexical(
        self,
        query: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        project_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 10,
    ) -> list[ScoredWorkingMemory]:
        """Indexed BM25 recall only (the term that never needs an embedder)."""
        ...

    async def recall_vector(
        self,
        query_embedding: list[float],
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        project_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 10,
    ) -> list[ScoredWorkingMemory]:
        """Stored-vector recall against a caller-supplied query embedding."""
        ...

    async def lookup_entity(self, name: str) -> EntityRecord | None:
        """One entity by normalized name, with its MentionedIn memories."""
        ...

    async def relations_for(self, name: str) -> list[RelationRecord]:
        """Edges touching one entity, strongest first."""
        ...

    async def traverse(self, start_entity: str, *, max_depth: int = 2) -> TraversalResult:
        """Bounded BFS from an entity over working-graph edges."""
        ...

    async def entity_context(
        self,
        *,
        project_id: str | None = None,
        limit_entities: int = 8,
        memories_per_entity: int = 3,
    ) -> list[EntityContext]:
        """Graph context for Layer 4: top entities, relations, citing memories.

        ``project_id`` narrows the citing memories; the entities themselves
        span the Workspace because the working graph does.
        """
        ...

    async def reset(self) -> None:
        """Discard all content, keeping the workspace identity (corruption path)."""
        ...


@dataclass
class _WorkspaceCounters:
    """Mutable bookkeeping behind the frozen stats snapshot."""

    hydrated_total: int = 0
    updated_total: int = 0
    deleted_total: int = 0
    embedding_failures: int = 0
    rebuilds: int = 0
    last_hydrated_at: datetime | None = None
