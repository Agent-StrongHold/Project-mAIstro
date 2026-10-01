"""In-process indexed working-memory projection (ADR-082226-5104 §5-6).

The first implementation of the :class:`~maistro.memory.working.protocol.WorkingMemory`
protocol. It is the shape a LadybugDB-backed adapter will take — one graph per
Workspace, single writer, lazy and evictable — implemented on the primitives
MAIstro already trusts: BM25 over a tokenised inverted index, embeddings stored
at write time, and an entity graph with ``MentionedIn`` and co-occurrence edges.

Why an in-process implementation first: ADR-039's substrate constraint applies
to engine dependencies, and ``ladybugdb`` is not currently resolvable from the
package registry (review note in ``docs/architecture/working-memory.md``). The
protocol above is the adoption seam — swapping this class for a LadybugDB
adapter changes nothing above it. The patterns reused from the Ladybug-Memory
design (BM25 + stored working-memory vectors + entity/mention graph) are
recorded in ``INSPIRATIONS.md``; no code is copied and no dependency is added.

What this class is not: authoritative. It holds no state the authoritative
:class:`~maistro.types.memory.EpisodicStore` cannot rebuild, it has no route to
any durable store, and it answers visibility questions with the same
:func:`~maistro.memory.scopes.matches_scope` predicate the durable stores use.

Single-writer by construction: every method runs on the owning event loop and
mutates only its own per-Workspace state, which is the property ADR-082226-5104
§5 relies on when it calls Ladybug's single-writer constraint "unremarkable for
one local runtime's active workspace".
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from itertools import combinations
from typing import TYPE_CHECKING

from maistro.memory.scopes import build_scope_filter, matches_scope
from maistro.memory.working.extraction import LexicalEntityExtractor
from maistro.memory.working.protocol import (
    DEFAULT_EMBEDDING_MODEL,
    EntityContext,
    EntityRecord,
    HydrationReport,
    RelationRecord,
    ScoredWorkingMemory,
    TraversalResult,
    WorkingMemoryStats,
    _WorkspaceCounters,
)

if TYPE_CHECKING:
    from maistro.memory.working.extraction import EntityExtractor
    from maistro.protocols.embeddings import EmbeddingClient
    from maistro.types.memory import EpisodicMemory

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")

#: Okapi BM25 parameters. k1 = 1.2 and b = 0.75 are the standard defaults
#: (Lucene's); there is no MAIstro corpus yet to tune against, and inventing
#: values would only make the first benchmark harder to interpret.
_BM25_K1 = 1.2
_BM25_B = 0.75

#: Bound on a traversal's visited set. A hot graph is small (one active
#: Workspace), but a bound is what makes a hostile cycle a bounded walk
#: instead of a hang.
_MAX_TRAVERSAL_NODES = 64


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _normalize_entity(name: str) -> str:
    return " ".join(name.split()).lower()


def _fingerprint(content: str, weight: float) -> str:
    return hashlib.sha256(f"{content}\x00{weight:.6f}".encode()).hexdigest()


def _cosine(a: list[float] | tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class WorkspaceWorkingMemoryProjection:
    """:class:`WorkingMemoryProtocol` for one Workspace, in this process.

    Content lives in an inverted index (BM25), a stored-embedding map (vector
    recall), and an entity graph (mentions + co-occurrence). Everything is
    derived from the authoritative :class:`EpisodicMemory` records passed to
    :meth:`hydrate` / :meth:`store`, so :meth:`reset` plus a re-hydrate is a
    full rebuild with nothing lost.
    """

    def __init__(
        self,
        *,
        workspace_id: str,
        embedding_client: EmbeddingClient | None = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        entity_extractor: EntityExtractor | None = None,
    ) -> None:
        self._workspace_id = workspace_id
        self._embeddings_client = embedding_client
        self._embedding_model = embedding_model
        self._extractor: EntityExtractor = entity_extractor or LexicalEntityExtractor()

        # memory_id -> authoritative snapshot. EpisodicMemory is mutable and
        # the durable store may mutate what it handed out, so the projection
        # keeps its own copy (the context dict is copied; everything else is
        # immutable scalars).
        self._records: dict[str, EpisodicMemory] = {}
        # memory_id -> fingerprint of (content, weight) at index time. What
        # makes re-hydration idempotent: a record whose durable state has not
        # moved is recognized, not re-processed.
        self._fingerprints: dict[str, str] = {}

        # BM25 inverted index: term -> {memory_id: term_frequency}.
        self._postings: dict[str, dict[str, int]] = {}
        self._doc_len: dict[str, int] = {}
        self._total_len = 0

        # Stored working-memory embeddings: memory_id -> vector. Written at
        # hydrate/store/update time, never recomputed during a read.
        self._embeddings: dict[str, tuple[float, ...]] = {}
        self._embedded_model: str = ""

        # Entity graph. normalized name -> {memory_id: surface label}; the
        # MentionedIn edges are exactly these memberships. Pair weights are
        # observation counts behind co-occurrence edges.
        self._entity_memories: dict[str, dict[str, str]] = {}
        self._relations: dict[tuple[str, str], float] = {}
        self._adjacency: dict[str, set[str]] = {}
        # memory_id -> normalized entity keys it contributed, so removal is
        # exact even for lexically-derived entities the extractor found.
        self._record_entities: dict[str, set[str]] = {}

        self._counters = _WorkspaceCounters()

    # ------------------------------------------------------------------
    # Identity / observability
    # ------------------------------------------------------------------

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def stats(self) -> WorkingMemoryStats:
        embedded = len(self._embeddings)
        client_ready = self._embeddings_client is not None
        model_consistent = not self._embeddings or self._embedded_model == self._embedding_model
        vector_ready = client_ready and embedded > 0 and model_consistent
        degraded = ""
        if self._embeddings_client is None:
            degraded = "no embedding client configured; vector recall unavailable (lexical active)"
        elif self._embeddings and not model_consistent:
            degraded = (
                f"stored vectors from model '{self._embedded_model}' do not match configured "
                f"'{self._embedding_model}'; vectors dropped pending re-embed"
            )
        elif self._counters.embedding_failures:
            degraded = (
                f"{self._counters.embedding_failures} embedding failures; "
                "affected records answer lexical-only until re-hydrated"
            )
        elif not embedded and self._records:
            degraded = "records indexed but not yet embedded"
        return WorkingMemoryStats(
            records=len(self._records),
            entities=len(self._entity_memories),
            relations=len(self._relations),
            index_terms=len(self._postings),
            embedded_records=embedded,
            embedding_model=self._embedding_model,
            vector_ready=vector_ready,
            degraded_reason=degraded,
            embedding_failures=self._counters.embedding_failures,
            last_hydrated_at=self._counters.last_hydrated_at,
            hydrated_total=self._counters.hydrated_total,
            updated_total=self._counters.updated_total,
            deleted_total=self._counters.deleted_total,
            rebuilds=self._counters.rebuilds,
        )

    # ------------------------------------------------------------------
    # Hydration / writes
    # ------------------------------------------------------------------

    async def hydrate(self, memories: list[EpisodicMemory]) -> HydrationReport:
        """Materialise authoritative records. Idempotent per (content, weight)."""
        report = HydrationReport(0, 0, 0, 0)
        for memory in memories:
            existing = self._records.get(memory.memory_id)
            if memory.deleted:
                if existing is not None:
                    self._remove(memory.memory_id)
                    report = replace(report, deleted=report.deleted + 1)
                continue
            fingerprint = _fingerprint(memory.content, memory.weight)
            if existing is not None and self._fingerprints.get(memory.memory_id) == fingerprint:
                report = replace(report, unchanged=report.unchanged + 1)
                continue
            if existing is not None:
                reuse = (
                    self._embeddings.get(memory.memory_id)
                    if existing.content == memory.content
                    and self._embedded_model == self._embedding_model
                    else None
                )
                await self._insert(memory, reuse_embedding=reuse)
                report = replace(report, updated=report.updated + 1)
                self._counters.updated_total += 1
            else:
                await self._insert(memory)
                report = replace(report, hydrated=report.hydrated + 1)
                self._counters.hydrated_total += 1
        self._counters.last_hydrated_at = datetime.now(UTC)
        return report

    async def store(self, memory: EpisodicMemory) -> None:
        if memory.deleted:
            return
        await self._insert(memory)
        self._counters.hydrated_total += 1

    async def update(
        self, memory_id: str, *, content: str | None = None, weight: float | None = None
    ) -> bool:
        existing = self._records.get(memory_id)
        if existing is None:
            return False
        new_content = existing.content if content is None else content
        new_weight = existing.weight if weight is None else weight
        reuse = (
            self._embeddings.get(memory_id)
            if new_content == existing.content and self._embedded_model == self._embedding_model
            else None
        )
        await self._insert(
            replace(existing, content=new_content, weight=new_weight), reuse_embedding=reuse
        )
        self._counters.updated_total += 1
        return True

    async def delete(self, memory_id: str) -> bool:
        if memory_id not in self._records:
            return False
        self._remove(memory_id)
        self._counters.deleted_total += 1
        return True

    async def reset(self) -> None:
        """Discard all content, keeping the workspace identity.

        The corruption/rebuild path (ADR-082226-5104 §6): everything this
        projection holds is derivable from the authoritative store, so
        throwing it away costs nothing durable. Lifetime counters survive —
        they are observability, not state.
        """
        self._records.clear()
        self._fingerprints.clear()
        self._postings.clear()
        self._doc_len.clear()
        self._total_len = 0
        self._embeddings.clear()
        self._embedded_model = ""
        self._entity_memories.clear()
        self._relations.clear()
        self._adjacency.clear()
        self._record_entities.clear()
        self._counters.rebuilds += 1

    # ------------------------------------------------------------------
    # Recall
    # ------------------------------------------------------------------

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
        visible = self._visible(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
            project_id=project_id,
            min_weight=min_weight,
        )
        if not visible or not query.strip():
            return []

        lex_raw = {
            mid: score for mid, score in self._bm25(_tokenize(query)).items() if mid in visible
        }
        vec_raw = {
            mid: score
            for mid, score in (await self._query_similarities(query)).items()
            if mid in visible
        }
        lex_max = max(lex_raw.values(), default=0.0)
        # Both terms share [0, 1] before the weight multiplier, for the reason
        # `ranking.py` documents: two terms only compose if they share a range.
        combined = {
            mid: (score / lex_max if lex_max > 0 else 0.0) + max(vec_raw.get(mid, 0.0), 0.0)
            for mid, score in lex_raw.items()
        }
        for mid, score in vec_raw.items():
            if mid not in combined:
                combined[mid] = max(score, 0.0)
        weighted = {mid: score * visible[mid].weight for mid, score in combined.items()}
        ranked = sorted(weighted.items(), key=lambda pair: (-pair[1], pair[0]))
        return [
            ScoredWorkingMemory(
                memory=visible[mid],
                lexical_score=(lex_raw.get(mid, 0.0) / lex_max if lex_max > 0 else 0.0),
                vector_score=max(vec_raw.get(mid, 0.0), 0.0),
            )
            for mid, total in ranked[:limit]
            if total > 0.0
        ]

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
        visible = self._visible(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
            project_id=project_id,
            min_weight=min_weight,
        )
        if not visible or not query.strip():
            return []
        lex_raw = {
            mid: score for mid, score in self._bm25(_tokenize(query)).items() if mid in visible
        }
        lex_max = max(lex_raw.values(), default=0.0)
        weighted = {
            mid: (score / lex_max if lex_max > 0 else 0.0) * visible[mid].weight
            for mid, score in lex_raw.items()
        }
        ranked = sorted(weighted.items(), key=lambda pair: (-pair[1], pair[0]))
        return [
            ScoredWorkingMemory(
                memory=visible[mid],
                lexical_score=(lex_raw[mid] / lex_max if lex_max > 0 else 0.0),
                vector_score=0.0,
            )
            for mid, total in ranked[:limit]
            if total > 0.0
        ]

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
        visible = self._visible(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
            project_id=project_id,
            min_weight=min_weight,
        )
        if not visible or not query_embedding:
            return []
        weighted = {
            memory_id: max(_cosine(query_embedding, stored), 0.0) * memory.weight
            for memory_id, memory in visible.items()
            if (stored := self._embeddings.get(memory_id)) is not None
        }
        ranked = sorted(weighted.items(), key=lambda pair: (-pair[1], pair[0]))
        return [
            ScoredWorkingMemory(memory=visible[mid], lexical_score=0.0, vector_score=score)
            for mid, score in ranked[:limit]
            if score > 0.0
        ]

    # ------------------------------------------------------------------
    # Entity graph
    # ------------------------------------------------------------------

    async def lookup_entity(self, name: str) -> EntityRecord | None:
        return self._entity_record(_normalize_entity(name))

    async def relations_for(self, name: str) -> list[RelationRecord]:
        return self._relations_for(_normalize_entity(name))

    async def traverse(self, start_entity: str, *, max_depth: int = 2) -> TraversalResult:
        """Bounded BFS from one entity over working-graph edges.

        Traversal cannot leave this projection: the adjacency map is an
        attribute of this object, and no operation reaches into another
        Workspace's projection. Isolation is structural, not policed.
        """
        start = _normalize_entity(start_entity)
        if start not in self._adjacency:
            return TraversalResult(visited=(), edges=())
        visited: list[str] = [start]
        seen = {start}
        edges: list[RelationRecord] = []
        frontier = [start]
        for _depth in range(max(0, max_depth)):
            nxt: list[str] = []
            for node in frontier:
                for neighbour in sorted(self._adjacency.get(node, ())):
                    edges.append(self._edge_record(node, neighbour))
                    if neighbour not in seen:
                        seen.add(neighbour)
                        visited.append(neighbour)
                        nxt.append(neighbour)
            frontier = nxt
            if not frontier or len(visited) >= _MAX_TRAVERSAL_NODES:
                break
        return TraversalResult(visited=tuple(visited[:_MAX_TRAVERSAL_NODES]), edges=tuple(edges))

    def records(self) -> list[EpisodicMemory]:
        """Every record, strongest first. A read-only view for Dreaming."""
        return sorted(self._records.values(), key=lambda m: (-m.weight, m.memory_id))

    def relation_pairs(self) -> list[tuple[str, str, float]]:
        """Every co-occurrence edge as (source, target, observation count)."""
        return sorted(
            ((a, b, weight) for (a, b), weight in self._relations.items()),
            key=lambda triple: (-triple[2], triple[0], triple[1]),
        )

    def entity_names(self) -> list[str]:
        """Every entity, most-mentioned first."""
        return sorted(
            self._entity_memories,
            key=lambda key: (-len(self._entity_memories[key]), key),
        )

    async def entity_context(
        self,
        *,
        project_id: str | None = None,
        limit_entities: int = 8,
        memories_per_entity: int = 3,
    ) -> list[EntityContext]:
        ranked = sorted(
            self._entity_memories.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
        contexts: list[EntityContext] = []
        for key, _mentions in ranked[:limit_entities]:
            record = self._entity_record(key)
            if record is None:
                continue
            citing = [
                self._records[mid]
                for mid in record.memory_ids
                if mid in self._records
                and (not project_id or self._records[mid].project_id == project_id)
            ]
            citing.sort(key=lambda m: (-m.weight, m.memory_id))
            contexts.append(
                EntityContext(
                    entity=record,
                    relations=tuple(self._relations_for(key)[:5]),
                    memories=tuple(citing[:memories_per_entity]),
                )
            )
        return contexts

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _visible(
        self,
        *,
        agent_id: str | None,
        user_id: str | None,
        team_id: str | None,
        org_id: str | None,
        project_id: str | None,
        min_weight: float,
    ) -> dict[str, EpisodicMemory]:
        """The scope predicate, verbatim from the durable stores.

        `build_scope_filter` + `matches_scope` are the one spelling of the
        visibility rule (ADR-083026-a322); a hot index that re-typed the
        clauses would be a second spelling of a leak. The same no-scope-axis
        rule applies: with no axis named, `project_id` alone selects, which
        is what project-changelog-style recall needs.
        """
        filters = build_scope_filter(
            agent_id=agent_id, user_id=user_id, team_id=team_id, org_id=org_id
        )
        no_scope_filter = not (agent_id or user_id or team_id or org_id)
        visible: dict[str, EpisodicMemory] = {}
        for memory_id, memory in self._records.items():
            if memory.deleted or memory.weight < min_weight:
                continue
            if not no_scope_filter and not matches_scope(memory, filters):
                continue
            if project_id and memory.project_id != project_id:
                continue
            visible[memory_id] = memory
        return visible

    def _bm25(self, query_terms: list[str]) -> dict[str, float]:
        """Okapi BM25 over the inverted index.

        Work is proportional to the matching postings, not to the corpus —
        this is the indexed path the acceptance criterion asks for, not a
        Python scan over every record's content.
        """
        n_docs = len(self._records)
        if not n_docs or not query_terms:
            return {}
        avgdl = self._total_len / n_docs
        scores: dict[str, float] = {}
        for term in set(query_terms):
            posting = self._postings.get(term)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            for memory_id, tf in posting.items():
                dl = self._doc_len.get(memory_id, 0)
                ratio = dl / avgdl if avgdl > 0 else 0.0
                denom = tf + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * ratio)
                scores[memory_id] = scores.get(memory_id, 0.0) + idf * tf * (_BM25_K1 + 1.0) / denom
        return scores

    async def _query_similarities(self, query: str) -> dict[str, float]:
        """Cosine against stored embeddings. The query embeds once; nothing else."""
        if self._embeddings_client is None or not self._embeddings:
            return {}
        try:
            query_vec = await self._embeddings_client.embed(query)
        except Exception:
            self._counters.embedding_failures += 1
            logger.warning(
                "working-memory[%s]: query embedding failed; answering lexical-only",
                self._workspace_id,
            )
            return {}
        return {
            memory_id: max(_cosine(query_vec, stored), 0.0)
            for memory_id, stored in self._embeddings.items()
        }

    async def _insert(
        self, memory: EpisodicMemory, *, reuse_embedding: tuple[float, ...] | None = None
    ) -> None:
        """Index one record, replacing any previous version of it.

        Every update path routes through remove-then-insert, which is what
        keeps the acceptance invariant "updating memory content cannot leave
        the working embedding/index describing the previous content": the old
        postings, entity edges and stored embedding are gone before the new
        content is indexed, and a failed re-embed leaves the record honestly
        vector-absent (counted and logged) rather than vector-stale.

        Entity extraction runs before anything is mutated: a governed
        extractor that fails leaves the projection exactly as it was, so a
        visible failure is also a clean one.
        """
        declared = self._declared_entities(memory)
        extracted = await self._extractor.extract(memory.content, declared=declared)
        keys = list(dict.fromkeys(_normalize_entity(name) for name in extracted if name.strip()))
        self._remove(memory.memory_id)
        snapshot = replace(memory, context=dict(memory.context))
        self._records[memory.memory_id] = snapshot
        self._fingerprints[memory.memory_id] = _fingerprint(memory.content, memory.weight)
        self._index_content(memory.memory_id, memory.content)
        self._attach_entities(memory.memory_id, keys)
        await self._embed_record(memory.memory_id, memory.content, reuse_embedding=reuse_embedding)

    def _declared_entities(self, memory: EpisodicMemory) -> list[str]:
        declared = memory.context.get("entities")
        names = declared if isinstance(declared, list) else []
        return [name for name in names if isinstance(name, str)]

    def _remove(self, memory_id: str) -> None:
        memory = self._records.pop(memory_id, None)
        if memory is None:
            return
        del self._fingerprints[memory_id]
        self._deindex_content(memory_id)
        self._deindex_entities(memory_id)
        self._embeddings.pop(memory_id, None)

    # -- BM25 index maintenance ----------------------------------------

    def _index_content(self, memory_id: str, content: str) -> None:
        terms = _tokenize(content)
        self._doc_len[memory_id] = len(terms)
        self._total_len += len(terms)
        for term, tf in Counter(terms).items():
            self._postings.setdefault(term, {})[memory_id] = tf

    def _deindex_content(self, memory_id: str) -> None:
        for term in list(self._postings):
            posting = self._postings[term]
            if memory_id in posting:
                del posting[memory_id]
                if not posting:
                    del self._postings[term]
        self._total_len -= self._doc_len.pop(memory_id, 0)

    # -- Entity graph maintenance --------------------------------------

    def _attach_entities(self, memory_id: str, keys: list[str]) -> None:
        """Write MentionedIn memberships and co-occurrence edges for one record."""
        self._record_entities[memory_id] = set(keys)
        for key in keys:
            mentions = self._entity_memories.setdefault(key, {})
            # Keep the first surface form as the label; a later mention does
            # not rewrite it.
            mentions.setdefault(memory_id, self._records[memory_id].content[:80])
            self._adjacency.setdefault(key, set())
        for a, b in combinations(sorted(keys), 2):
            self._relations[(a, b)] = self._relations.get((a, b), 0.0) + 1.0
            self._adjacency.setdefault(a, set()).add(b)
            self._adjacency.setdefault(b, set()).add(a)

    def _deindex_entities(self, memory_id: str) -> None:
        keys = self._record_entities.pop(memory_id, set())
        # Decrement every co-occurrence pair this record contributed first, so
        # edge weights are observation counts of records currently in the
        # graph, not of everything ever indexed.
        for a, b in combinations(sorted(keys), 2):
            remaining = self._relations.get((a, b), 0.0) - 1.0
            if remaining <= 0.0:
                self._relations.pop((a, b), None)
                self._adjacency.get(a, set()).discard(b)
                self._adjacency.get(b, set()).discard(a)
            else:
                self._relations[(a, b)] = remaining
        for key in keys:
            mentions = self._entity_memories.get(key)
            if mentions:
                mentions.pop(memory_id, None)
                if not mentions:
                    self._forget_entity(key)

    def _forget_entity(self, key: str) -> None:
        """Drop an entity no record mentions.

        Every pair involving `key` is already gone: the decrement loop above
        ran first, and a pair survives only while some record co-mentions
        both ends. Only the adjacency mirrors remain to clean.
        """
        self._entity_memories.pop(key, None)
        for neighbour in self._adjacency.pop(key, set()):
            self._adjacency.get(neighbour, set()).discard(key)

    def _entity_record(self, key: str) -> EntityRecord | None:
        mentions = self._entity_memories.get(key)
        if not mentions:
            return None
        label = next(iter(mentions.values()), key)
        return EntityRecord(
            name=key,
            label=label if len(label) <= 40 else f"{label[:37]}...",
            mention_count=len(mentions),
            memory_ids=tuple(sorted(mentions)),
        )

    def _relations_for(self, key: str) -> list[RelationRecord]:
        out: list[RelationRecord] = []
        for (a, b), weight in self._relations.items():
            if a == key:
                out.append(RelationRecord(source=a, target=b, kind="co_occurs_with", weight=weight))
            elif b == key:
                out.append(RelationRecord(source=b, target=a, kind="co_occurs_with", weight=weight))
        out.sort(key=lambda r: (-r.weight, r.target))
        return out

    def _edge_record(self, a: str, b: str) -> RelationRecord:
        weight = self._relations.get((min(a, b), max(a, b)), 0.0)
        return RelationRecord(source=a, target=b, kind="co_occurs_with", weight=weight)

    # -- Embedding maintenance -----------------------------------------

    async def _embed_record(
        self,
        memory_id: str,
        content: str,
        *,
        reuse_embedding: tuple[float, ...] | None = None,
    ) -> None:
        """Store this record's embedding — or honestly store none.

        The stale-vector rule: `_insert` removed any previous embedding before
        this ran, so a failed embed leaves the record lexically indexed and
        vector-absent — counted, logged, and visible in
        :attr:`WorkingMemoryStats.degraded_reason` — never vector-stale.

        `reuse_embedding` carries a vector across a weight-only update: the
        content did not move, so paying an embed call would be waste, and the
        result would describe exactly the content it already describes.
        """
        if reuse_embedding is not None:
            self._embeddings[memory_id] = reuse_embedding
            self._embedded_model = self._embedding_model
            return
        if self._embeddings_client is None:
            return
        # Model-identity guard: vectors from a different configured model are
        # stale by definition (the working projection is disposable, but the
        # choice of model must be explicit — issue #301 safeguard).
        if self._embeddings and self._embedded_model != self._embedding_model:
            logger.warning(
                "working-memory[%s]: dropping %d vectors from model '%s' (configured '%s')",
                self._workspace_id,
                len(self._embeddings),
                self._embedded_model,
                self._embedding_model,
            )
            self._embeddings.clear()
        try:
            vector = await self._embeddings_client.embed(content)
        except Exception:
            self._counters.embedding_failures += 1
            self._embeddings.pop(memory_id, None)
            logger.warning(
                "working-memory[%s]: embedding failed for %s; record answers lexical-only",
                self._workspace_id,
                memory_id,
            )
            return
        self._embeddings[memory_id] = tuple(vector)
        self._embedded_model = self._embedding_model
