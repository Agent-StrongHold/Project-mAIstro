"""M8-C1 research harness — hybrid vector + graph retrieval vs vector-only.

Issue #920 (leaf of epic #901, initiative #879). Hypothesis under study:
combining semantic vector retrieval with explicit entity/relation traversal
improves recall and evidence quality for long-lived Workspace questions enough
to justify added graph complexity.

This module is a RESEARCH ARTIFACT, not product code. It implements the
measurement machinery the #920 benchmark procedure demands — a deterministic
synthetic Workspace-history corpus (entities, projects, decisions, dependency
chains, temporal facts, supersession, cross-document relations) with ground
truth by construction; vector-only, recency-weighted, and bounded hybrid
vector→graph strategies; recall/precision/evidence-sufficiency scoring;
provenance-chain completeness; deterministic work-unit latency accounting;
storage/index cost; graph-construction error; and stale-fact / incorrect-edge
sensitivity — so the real experiment is reproducible the moment real Workspace
histories and a real embedder are available.

What the fixtures are and are not:

- The hand-checked fixture declares its embedding table explicitly (unit
  vectors over five orthogonal concept axes) so every cosine, rank, and fused
  score is verifiable by hand arithmetic in the test comments. It validates
  the *machinery*.
- The seeded corpus uses a hashed bag-of-words embedder — the same offline
  convention as ``scripts/bench_working_memory.py`` — so structure-driven
  effects scale beyond the hand case. Its assertions are the ones construction
  guarantees (determinism, degeneration equalities, direction of family-level
  deltas), never hoped-for quality numbers.
- NEITHER is experimental evidence about real embeddings, real extraction, or
  real Workspace histories. Numbers from this harness must never be quoted as
  such. The real-experiment procedure lives in
  ``docs/research/920-hybrid-vector-graph-retrieval.md``.

Strategy shape (what "bounded hybrid" means here): vector candidates →
*query-anchored* one-hop traversal of typed dependency edges → fusion.
Anchoring expands only through entities the query itself names, and per-query
expansion ADMISSIONS are bounded by the expansion budget — but the traversal
SCAN is not: enumerating an anchor's dependency targets and their membership
entries costs work that grows with the graph, so the latency accounting
charges admissions AND inspections and no test certifies latency by the
budget alone. With the budget at zero (and demotion off) the hybrid is
exactly its vector baseline — the degeneration the tests pin, so "hybrid"
can never quietly be something else.

Trust boundary (the epic contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing reads or writes a
  Goal, a Run authority, a durable memory store, or any authorization path.
  The module imports no maistro module at all, so it cannot become a second
  canonical memory authority by accident — the exact prohibition the issue
  states. Production adoption of any strategy found here routes to the
  canonical memory owners (ADR-034, ADR-091, ADR-082226-5104), never through
  this harness.
- Ground truth is a property of the fixture corpus, recorded at construction
  and frozen; scoring compares frozen sets, so results cannot be mutated into
  authorization after the fact.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-C1 output as
#: authorization. Durable memory authority remains PostgreSQL + pgvector
#: (ADR-011/ADR-034); graph structures remain disposable projections
#: (ADR-082226-5104).
ADVISORY_ONLY = True


# ---------------------------------------------------------------------------
# Corpus records — one synthetic Workspace history with ground truth
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryRecord:
    """One memory in the synthetic Workspace history.

    ``day`` is the temporal position (integer, deterministic). ``entities``
    are the *ground-truth* mentions — what the history actually concerns —
    which extraction is allowed to get wrong. ``weight`` follows the ADR-091
    tier-weight axis (0.1-1.0) so recency/weight policies exercise realistic
    magnitudes.
    """

    memory_id: str
    text: str
    day: int
    entities: frozenset[str]
    project: str | None
    kind: str  # "fact" | "decision" | "observation"
    weight: float

    def __post_init__(self) -> None:
        if not self.memory_id:
            raise ValueError("memory_id must be non-empty")
        if self.day < 0:
            raise ValueError(f"{self.memory_id}: negative day")
        if not 0.1 <= self.weight <= 1.0:
            raise ValueError(f"{self.memory_id}: weight {self.weight} outside the ADR-091 band")


@dataclass(frozen=True)
class Dependency:
    """One ground-truth typed dependency: ``src`` depends on ``dst``."""

    src: str
    dst: str
    day: int


@dataclass(frozen=True)
class Supersession:
    """One ground-truth supersession: ``current`` supersedes ``stale``."""

    current: str
    stale: str
    day: int


@dataclass(frozen=True)
class Query:
    """One judged question over the history.

    ``relevant`` is the frozen ground-truth evidence set (by construction:
    the records the history says answer the question). ``stale`` lists
    known-stale records a correct answer must NOT lead with — the stale-fact
    axis of the issue's measure list.
    """

    query_id: str
    text: str
    family: str  # "direct" | "relational" | "temporal"
    relevant: frozenset[str]
    stale: frozenset[str] = frozenset()


@dataclass(frozen=True)
class WorkspaceHistory:
    """A synthetic Workspace history plus its ground truth."""

    workspace_id: str
    records: tuple[MemoryRecord, ...]
    dependencies: tuple[Dependency, ...]
    supersessions: tuple[Supersession, ...]
    queries: tuple[Query, ...]
    now_day: int

    @property
    def record_ids(self) -> frozenset[str]:
        return frozenset(r.memory_id for r in self.records)


def _validate_history(history: WorkspaceHistory) -> None:
    """Reject malformed fixtures loudly — a silent fix would fake evidence."""
    if not history.records:
        raise ValueError("empty corpus: a benchmark over nothing measures nothing")
    ids = history.record_ids
    if len(ids) != len(history.records):
        raise ValueError("duplicate memory ids in corpus")
    _validate_query_ids(history.queries)
    _validate_query_ground_truth(history, ids)
    _validate_relations(history, ids)


def _validate_query_ids(queries: tuple[Query, ...]) -> None:
    """Query ids must be unique before any embedding is cached by id.

    A retriever caches per-query vectors keyed by ``query_id``; a duplicate
    id would silently overwrite the first query's vector with the second's
    and then score both queries against that last vector — plausible-looking
    recall numbers from a malformed query set, with nothing raising.
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    for query in queries:
        if query.query_id in seen and query.query_id not in duplicates:
            duplicates.append(query.query_id)
        seen.add(query.query_id)
    if duplicates:
        raise ValueError(f"duplicate query ids: {sorted(duplicates)}")


def _validate_query_ground_truth(history: WorkspaceHistory, ids: frozenset[str]) -> None:
    """Every query's relevant/stale sets must name real, disjoint records."""
    for q in history.queries:
        unknown = q.relevant - ids
        if unknown:
            raise ValueError(f"query {q.query_id}: relevant ids not in corpus: {sorted(unknown)}")
        unknown_stale = q.stale - ids
        if unknown_stale:
            raise ValueError(
                f"query {q.query_id}: stale ids not in corpus: {sorted(unknown_stale)}"
            )
        overlap = q.relevant & q.stale
        if overlap:
            raise ValueError(f"query {q.query_id}: {sorted(overlap)} both relevant and stale")


def _validate_relations(history: WorkspaceHistory, ids: frozenset[str]) -> None:
    """Edges must connect distinct, existing nodes; supersession must be real.

    A dependency endpoint no record mentions is rejected, not silently kept:
    it has no membership node, so traversal could never reach it, yet it
    would still be counted as ground truth by ``graph_construction_error`` —
    corrupting both the recall and the construction-error measurements it
    feeds.
    """
    entities = {e for r in history.records for e in r.entities}
    for dep in history.dependencies:
        if dep.src == dep.dst:
            raise ValueError(f"self-dependency {dep.src}")
        unknown = {dep.src, dep.dst} - entities
        if unknown:
            raise ValueError(
                f"dependency {dep.src}->{dep.dst} names entities no record mentions: "
                f"{sorted(unknown)}"
            )
    for sup in history.supersessions:
        if sup.current not in ids or sup.stale not in ids:
            raise ValueError(f"supersession {sup.current}->{sup.stale} names unknown records")
        if sup.current == sup.stale:
            raise ValueError("record supersedes itself")


# ---------------------------------------------------------------------------
# Embedders — the stand-in for a real embedding model
# ---------------------------------------------------------------------------


class Embedder:
    """Text/vector interface both fixture embedders satisfy.

    A real experiment injects the governed embedding client's outputs here;
    nothing else in the harness changes (the same substitution the real seam
    makes behind ``EmbeddingClient``).
    """

    def dimension(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def embed(self, text: str) -> tuple[float, ...]:  # pragma: no cover - interface
        raise NotImplementedError


class TableEmbedder(Embedder):
    """Explicit vector per text — the hand-checked fixture's "model".

    Every fixture vector is declared in the test data with its arithmetic
    worked out in comments, so no hashed-collision ambiguity can hide a wrong
    expected ranking.
    """

    def __init__(self, table: dict[str, tuple[float, ...]]) -> None:
        self._table = dict(table)
        dims = {len(v) for v in self._table.values()}
        if len(dims) != 1:
            raise ValueError(f"table vectors must share one dimension, got {sorted(dims)}")
        self._dim = dims.pop()

    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> tuple[float, ...]:
        try:
            return self._table[text]
        except KeyError:
            msg = (
                f"no fixture vector declared for {text!r}; the hand-checked "
                "fixture must declare every vector it scores"
            )
            raise KeyError(msg) from None


class HashEmbedder(Embedder):
    """Deterministic hashed bag-of-words, L2-normalized.

    The same offline convention as ``scripts/bench_working_memory.py``:
    tokens are lowercased, split on non-letters, stripped of a trailing
    plural ``s``; each token seeds one dimension via blake2b. No semantic
    structure — which is exactly why relational evidence (records sharing no
    token with the query) is invisible to vector-only retrieval on the seeded
    corpus, and why the builder asserts that property textually rather than
    trusting the embedder to preserve it.
    """

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dimension must be positive")
        self._dim = dim

    def dimension(self) -> int:
        return self._dim

    @staticmethod
    def tokens(text: str) -> list[str]:
        out: list[str] = []
        buf: list[str] = []
        for ch in text.lower():
            if ch.isalpha():
                buf.append(ch)
            elif buf:
                out.append("".join(buf))
                buf = []
        if buf:
            out.append("".join(buf))
        return [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in out]

    def embed(self, text: str) -> tuple[float, ...]:
        vec = [0.0] * self._dim
        for token in self.tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self._dim
            vec[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return tuple(vec)
        return tuple(v / norm for v in vec)


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Cosine similarity; zero-vector inputs score 0.0, never NaN."""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _unit(vec: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        raise ValueError("cannot normalize a zero vector")
    return tuple(v / norm for v in vec)


# ---------------------------------------------------------------------------
# Graph construction — extraction with controllable error
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedGraph:
    """What the (simulated) extractor built from the history.

    A *disposable projection* in the ADR-082226-5104 sense: derived views
    over records, no durable truth of its own. ``memberships`` maps entity →
    record ids mentioning it; ``dependencies`` is the extracted typed edge
    set (src depends on dst); ``supersedes`` maps stale record id → the id
    superseding it; ``spurious_dependencies`` are edges extraction invented
    outright, kept separate for the spur accounting.
    """

    memberships: dict[str, frozenset[str]]
    dependencies: frozenset[tuple[str, str]]
    supersedes: dict[str, str]
    spurious_dependencies: frozenset[tuple[str, str]]

    def records_for(self, entity: str) -> frozenset[str]:
        """Records mentioning ``entity`` under the extracted memberships."""
        return self.memberships.get(entity, frozenset())

    def dependents(self, entity: str) -> frozenset[str]:
        """Entities typed as depending on ``entity`` (the impact direction)."""
        return frozenset(src for src, dst in self.dependencies if dst == entity)

    def depends_on(self, entity: str) -> frozenset[str]:
        """Entities ``entity`` typed as depending on (the blast-radius direction)."""
        return frozenset(dst for src, dst in self.dependencies if src == entity)


@dataclass(frozen=True)
class ExtractionErrorRates:
    """Controllable graph-construction error.

    All rates are probabilities in [0, 1]. ``mention_drop`` drops a true
    entity mention; ``mention_spur`` invents a mention of an unrelated
    entity; ``edge_miss`` drops a true dependency; ``edge_spur`` rewrites a
    true dependency's destination to a random other entity. At the all-zero
    default the extraction is exactly the ground truth.
    """

    mention_drop: float = 0.0
    mention_spur: float = 0.0
    edge_miss: float = 0.0
    edge_spur: float = 0.0

    def __post_init__(self) -> None:
        for name in ("mention_drop", "mention_spur", "edge_miss", "edge_spur"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {value}")


def extract_graph(
    history: WorkspaceHistory, rates: ExtractionErrorRates, seed: int
) -> ExtractedGraph:
    """Build the projection graph, injecting exactly the requested error.

    The error model is the measurement instrument, not a claim about any real
    extractor: real construction error is whatever the real extraction path
    produces; this generator lets the sensitivity sweep hold error at named
    rates so degradation is attributable.
    """
    entities = sorted({e for r in history.records for e in r.entities})
    rng = random.Random(seed)

    memberships: dict[str, set[str]] = {e: set() for e in entities}
    for record in history.records:
        for entity in sorted(record.entities):
            if rng.random() < rates.mention_drop:
                continue
            memberships[entity].add(record.memory_id)
        if rates.mention_spur > 0.0:
            #: Pick from entities the record does NOT already mention, after
            #: the fire-draw: a pick from all entities could land on a true
            # mention, inject nothing, and leave even mention_spur = 1.0 with
            # no error on records that mention everything — the realized rate
            # would then vary with mention breadth instead of matching the
            # requested one.
            outside = [e for e in entities if e not in record.entities]
            if outside and rng.random() < rates.mention_spur:
                memberships[rng.choice(outside)].add(record.memory_id)

    dependencies: set[tuple[str, str]] = set()
    spurious: set[tuple[str, str]] = set()
    for dep in history.dependencies:
        if rng.random() < rates.edge_miss:
            continue
        edge = (dep.src, dep.dst)
        if rates.edge_spur > 0.0 and len(entities) > 1 and rng.random() < rates.edge_spur:
            rerouted = rng.choice([e for e in entities if e != dep.dst])
            edge = (dep.src, rerouted)
            spurious.add(edge)
        dependencies.add(edge)

    supersedes = {s.stale: s.current for s in history.supersessions}
    return ExtractedGraph(
        memberships={e: frozenset(ids) for e, ids in memberships.items()},
        dependencies=frozenset(dependencies),
        supersedes=supersedes,
        spurious_dependencies=frozenset(spurious),
    )


def graph_construction_error(history: WorkspaceHistory, graph: ExtractedGraph) -> dict[str, float]:
    """Miss/spur rates of an extracted graph against ground truth.

    The issue's graph-construction-error numbers: how much of the true
    relation set survived extraction, and how much of what extraction
    produced was never true. Both are against the fixture's frozen ground
    truth — in a real experiment, against a hand-audited sample.
    """
    truth = {(d.src, d.dst) for d in history.dependencies}
    extracted = set(graph.dependencies)
    miss = len(truth - extracted) / len(truth) if truth else 0.0
    spur = len(extracted - truth) / len(extracted) if extracted else 0.0
    return {
        "edge_miss_rate": miss,
        "edge_spur_rate": spur,
        "true_edges": float(len(truth)),
        "extracted_edges": float(len(extracted)),
        "correct_edges": float(len(truth & extracted)),
    }


# ---------------------------------------------------------------------------
# Retrieval strategies
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProvenanceStep:
    """One hop of an expansion's provenance chain.

    ``from_memory`` is the candidate whose score admitted the expansion;
    ``via_entity`` is the entity whose membership set was consulted;
    ``relation`` names the edge relation used. An expansion hit with an empty
    chain is a provenance defect — the metric exists to catch exactly that in
    a real implementation, where truncation or dedup can orphan an expanded
    hit from its justification.
    """

    from_memory: str
    via_entity: str
    relation: str


@dataclass(frozen=True)
class Hit:
    """One returned record with its score and provenance chain."""

    memory_id: str
    score: float
    provenance: tuple[ProvenanceStep, ...] = ()
    #: How the hit entered the result — decided at admission time and kept
    #: independent of the chain's contents. A hit admitted by expansion stays
    #: ``expanded`` even if its chain is later found defective, so a dropped
    #: chain is measured as the defect it is instead of being reclassified as
    #: a direct hit that needs no chain (which would let provenance
    #: completeness report a perfect 1.0 across exactly the bug it exists to
    #: catch).
    origin: str = "direct"

    def __post_init__(self) -> None:
        if self.origin not in ("direct", "expanded"):
            raise ValueError(f"unknown hit origin {self.origin!r}")

    @property
    def is_expanded(self) -> bool:
        return self.origin == "expanded"


@dataclass(frozen=True)
class RetrievalResult:
    """Frozen strategy output: ordered hits plus the work accounting.

    ``work_units`` counts deterministic operations (embedding lookups, cosine
    evaluations, expansion admissions) — the latency *proxy* this offline
    harness reports; expansion work is counted per admitted candidate, so it
    is bounded by the budget no matter how large the graph is. Wall-clock
    p50/p95 on the real seam is a real-experiment measurement (the in-tree
    baseline ``docs/benchmarks/working-memory-baseline.json`` already holds
    such numbers for the projection's lexical/hybrid/traverse paths).
    """

    hits: tuple[Hit, ...]
    work_units: int
    strategy: str
    #: Expansion accounting, reported separately so a latency claim cannot be
    #: certified by the budget alone. ``expansion_admissions`` (new candidates
    #: fused in) is capped by the expansion budget. ``expansion_inspected`` —
    #: dependency targets and membership entries the traversal enumerated,
    #: whether or not anything was admitted — is NOT: it grows with the
    #: graph's edge/membership surface however tight the budget is, and both
    #: are charged to ``work_units``.
    expansion_admissions: int = 0
    expansion_inspected: int = 0

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(h.memory_id for h in self.hits)


@dataclass(frozen=True)
class StrategyConfig:
    """Knobs shared by the strategies under comparison.

    ``candidate_pool`` bounds vector candidate generation (P);
    ``expansion_budget`` bounds total graph-expansion admissions per query
    (B) — the bound that keeps hybrid work independent of graph size;
    ``expansion_weight`` (beta) scales fused expansion scores;
    ``recency_half_life`` is the linear-recency decay divisor in days;
    ``supersession_gamma`` (gamma) demotes a returned hit that another returned
    hit supersedes.
    """

    candidate_pool: int = 4
    expansion_budget: int = 6
    expansion_weight: float = 1.25
    recency_half_life: float = 30.0
    supersession_gamma: float = 1.0

    def __post_init__(self) -> None:
        if self.candidate_pool < 0:
            raise ValueError("candidate_pool must be >= 0")
        if self.expansion_budget < 0:
            raise ValueError("expansion_budget must be >= 0")
        if self.expansion_weight < 0.0:
            raise ValueError("expansion_weight must be >= 0")
        if self.recency_half_life <= 0.0:
            raise ValueError("recency_half_life must be > 0")
        if not 0.0 <= self.supersession_gamma <= 1.0:
            raise ValueError("supersession_gamma must be in [0, 1]")


class WorkspaceRetriever:
    """Strategies over one synthetic history. Read-only; ground truth frozen."""

    def __init__(
        self,
        history: WorkspaceHistory,
        embedder: Embedder,
        graph: ExtractedGraph | None = None,
        config: StrategyConfig | None = None,
    ) -> None:
        _validate_history(history)
        self._history = history
        self._embedder = embedder
        self._graph = graph
        self._config = config or StrategyConfig()
        self._record_by_id: dict[str, MemoryRecord] = {r.memory_id: r for r in history.records}
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._query_vectors: dict[str, tuple[float, ...]] = {}
        #: Reverse membership view of the *extracted* graph: record id → the
        #: entities the graph says it mentions. Anchoring reads this, never
        #: the ground-truth ``record.entities`` — a mention the extractor
        #: dropped must break anchoring exactly as it would on the real seam,
        #: otherwise the harness leaks fixture truth into retrieval and
        #: understates the cost of mention-extraction failures.
        self._extracted_mentions: dict[str, frozenset[str]] = {}
        if graph is not None:
            mentions: dict[str, set[str]] = {}
            for entity, members in graph.memberships.items():
                for member in members:
                    mentions.setdefault(member, set()).add(entity)
            self._extracted_mentions = {
                rid: frozenset(entities) for rid, entities in mentions.items()
            }
        work = 0
        for record in history.records:
            self._vectors[record.memory_id] = embedder.embed(record.text)
            work += 1
        for query in history.queries:
            self._query_vectors[query.query_id] = embedder.embed(query.text)
            work += 1
        #: One-time index cost, exposed separately from per-query work.
        self.index_work_units = work

    @property
    def history(self) -> WorkspaceHistory:
        return self._history

    def run(self, strategy: str, query: Query, k: int) -> RetrievalResult:
        """Dispatch by name so evaluation code never touches privates."""
        methods = {
            "vector_only": self.vector_only,
            "vector_recency": self.vector_recency,
            "hybrid": self.hybrid,
        }
        try:
            method = methods[strategy]
        except KeyError:
            msg = f"unknown strategy {strategy!r}; known: {sorted(methods)}"
            raise ValueError(msg) from None
        return method(query, k)

    # -- scoring primitives ------------------------------------------------

    def _recency_factor(self, record: MemoryRecord) -> float:
        age = max(0, self._history.now_day - record.day)
        return 1.0 / (1.0 + age / self._config.recency_half_life)

    def _vector_ranking(self, query: Query) -> list[tuple[str, float]]:
        """Cosine over the whole corpus, descending, id-ascending on ties."""
        qvec = self._query_vectors[query.query_id]
        scored = [(rid, cosine(qvec, self._vectors[rid])) for rid in sorted(self._vectors)]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored

    def _vector_work(self) -> int:
        """N cosine evaluations plus the sort's comparison floor."""
        return len(self._vectors) + max(1, math.ceil(math.log2(len(self._vectors) + 1)))

    # -- strategies ---------------------------------------------------------

    def vector_only(self, query: Query, k: int) -> RetrievalResult:
        """Cosine top-k with the durable similarity seam's exact semantics.

        ``PgLearningStore.find_similar`` scope-filters, orders by cosine
        distance (``<=>``) and applies ``LIMIT`` — with *no*
        positive-similarity predicate — so records with zero (or negative)
        cosine inside the window are returned too. The baseline keeps them:
        dropping zero-similarity rows would flatter vector-only recall by
        declaring structurally-reachable evidence unreachable, and break
        baseline equivalence with the real seam this strategy stands in for.
        """
        if k <= 0:
            raise ValueError("k must be >= 1")
        scored = self._vector_ranking(query)
        hits = tuple(Hit(memory_id=rid, score=round(score, 12)) for rid, score in scored[:k])
        return RetrievalResult(hits=hits, work_units=self._vector_work(), strategy="vector_only")

    def vector_recency(self, query: Query, k: int) -> RetrievalResult:
        """Cosine  x  ADR-091 weight  x  linear recency decay, top-k.

        A HYPOTHETICAL control, deliberately labeled as one: the shipped
        indexed vector seam scores ``max(cosine, 0) x weight`` with no
        recency term, and its composed recall adds lexical and vector terms
        instead (``maistro/memory/working/indexed.py`` — ``recall_vector`` /
        ``recall``). This strategy asks what a recency column would buy on
        the stale-fact axis; its numbers are not the current policy's, and
        must not be quoted as such.

        Zero-similarity rows score exactly 0.0 under any multiplier and are
        cut, matching the projection seam's own ``score > 0`` output filter
        (unlike ``vector_only``, whose durable-seam semantics return them).
        """
        if k <= 0:
            raise ValueError("k must be >= 1")
        weighted = []
        for rid, sim in self._vector_ranking(query):
            record = self._record_by_id[rid]
            weighted.append((rid, sim * record.weight * self._recency_factor(record)))
        weighted.sort(key=lambda pair: (-pair[1], pair[0]))
        hits = tuple(
            Hit(memory_id=rid, score=round(score, 12)) for rid, score in weighted[:k] if score > 0.0
        )
        #: re-scoring every candidate costs one more pass than vector_only.
        work = self._vector_work() + len(self._vectors)
        return RetrievalResult(hits=hits, work_units=work, strategy="vector_recency")

    def hybrid(self, query: Query, k: int) -> RetrievalResult:
        """Vector candidates → query-anchored one-hop expansion → fusion.

        Per query:

        1. take the top ``candidate_pool`` vector hits (recency-blind, so the
           graph mechanism — not the recency heuristic — owns any gain);
        2. anchor on the entities the query text itself names (anchoring is
           what keeps expansion bounded by the query's entity surface);
        3. for each candidate in deterministic order (score desc, id asc),
           follow the anchor's typed dependency edges in both directions and
           admit new records from the neighbor entities' memberships until
           the expansion budget is spent; every admitted record inherits a
           provenance chain naming the source candidate, entity, relation;
        4. fuse: ``score = beta  x  (admitting candidate's vector score)``;
        5. optionally demote a fused candidate that another fused candidate
           supersedes (x gamma) over the FULL candidate set, then re-sort
           once — before any window cut, so the repair holds at small k;
        6. return top-k.

        With ``expansion_budget = 0`` (and gamma = 1) this is exactly
        ``vector_only`` restricted to its pool — pinned by a test.
        """
        if k <= 0:
            raise ValueError("k must be >= 1")
        if self._graph is None:
            raise ValueError("hybrid retrieval requires an extracted graph")
        cfg = self._config
        scored = self._vector_ranking(query)
        #: A request for k results must consider at least k candidates, so
        #: the pool bound is a floor of k — ``candidate_pool`` bounds extra
        #: exploration beyond what the caller asked for, never the request
        #: itself (otherwise the budget-0 degeneration to vector_only is
        #: not exact: hybrid would return fewer than k hits). The pool keeps
        #: zero-similarity rows for the same reason the baseline does: the
        #: degeneration must be exact, row for row.
        pool_size = max(cfg.candidate_pool, k)
        pool = scored[:pool_size]
        pool_ids = {rid for rid, _ in pool}
        pool_scores = dict(pool)
        work = self._vector_work()

        expansion_best, admissions, inspected = self._expand_candidates(
            query, pool, pool_ids, pool_scores
        )
        work += admissions + inspected

        fused_scores: dict[str, float] = {}
        provenance: dict[str, tuple[ProvenanceStep, ...]] = {}
        origins: dict[str, str] = {}
        for rid, score in pool:
            fused_scores[rid] = score
            provenance[rid] = ()
            origins[rid] = "direct"
        for member, (fused, step) in expansion_best.items():
            fused_scores[member] = fused_scores.get(member, 0.0) + fused
            provenance[member] = (*provenance.get(member, ()), step)
            origins[member] = "expanded"

        #: Demotion sees the FULL fused candidate set, not the truncated
        #: window: a superseding record one slot outside top-k must still
        #: demote the stale hit inside it, or the repair silently fails at
        #: exactly the small windows a stale-lead question asks with.
        ranked = sorted(fused_scores.items(), key=lambda pair: (-pair[1], pair[0]))
        ranked = self._demote_superseded(ranked)
        hits = tuple(
            Hit(
                memory_id=rid,
                score=round(score, 12),
                provenance=provenance[rid],
                origin=origins[rid],
            )
            for rid, score in ranked[:k]
        )
        return RetrievalResult(
            hits=hits,
            work_units=work,
            strategy="hybrid",
            expansion_admissions=admissions,
            expansion_inspected=inspected,
        )

    def _expand_candidates(
        self,
        query: Query,
        pool: list[tuple[str, float]],
        pool_ids: set[str],
        pool_scores: dict[str, float],
    ) -> tuple[dict[str, tuple[float, ProvenanceStep]], int, int]:
        """Bounded query-anchored one-hop expansion over dependency edges.

        Returns the best (score, provenance step) per admitted member, the
        admission count, and the traversal inspection count. Admissions are
        capped by the expansion budget; inspections are NOT — enumerating an
        anchor's dependency targets and their membership entries is real
        work the latency accounting must charge whether or not anything new
        is admitted, so reported latency cannot be certified by the budget
        alone while the scan itself scales with the graph. (The scan cannot
        stop at budget exhaustion anyway: enumerating a target's membership
        is what makes the scan a scan.)

        Anchoring: only entities the query text itself names are traversed,
        and — through the extracted reverse-membership view — only
        candidates the *graph* still says mention them. A mention the
        extractor dropped breaks the anchor the way it would on the real
        seam; ground truth is never consulted here. Only the impact
        direction (who depends on the anchor) is followed. The "what breaks
        if X changes" question is answered by X's dependents' evidence;
        following what X itself depends on pulls blast-radius noise that
        competes with (and on the seeded corpus crowds out) the impact
        evidence.

        Admission rule: any record the traversal reaches is admitted unless
        it is already a POSITIVE-similarity pool member — those stand on
        their own vector evidence. A zero-similarity pool member CAN be
        rescued: the graph's fused term replaces its carried 0.0, which is
        exactly the mechanism's point (the seam returned the record; the
        graph supplies the reason it matters).
        """
        assert self._graph is not None  # callers check; narrows for mypy
        cfg = self._config
        query_text = query.text.lower()
        anchors = {entity for entity in self._graph.memberships if entity in query_text}
        expansion_best: dict[str, tuple[float, ProvenanceStep]] = {}
        inspected = 0
        budget = cfg.expansion_budget
        for rid, source_score in pool:
            for anchor in sorted(self._extracted_mentions.get(rid, frozenset()) & anchors):
                for target in sorted(self._graph.dependents(anchor)):
                    inspected += 1
                    for member in sorted(self._graph.records_for(target)):
                        inspected += 1
                        if member in expansion_best:
                            continue
                        if member in pool_ids and pool_scores[member] > 0.0:
                            continue
                        if budget <= 0:
                            continue
                        budget -= 1
                        step = ProvenanceStep(
                            from_memory=rid, via_entity=target, relation="dependency"
                        )
                        expansion_best[member] = (cfg.expansion_weight * source_score, step)
        return expansion_best, cfg.expansion_budget - budget, inspected

    def _demote_superseded(self, ranked: list[tuple[str, float]]) -> list[tuple[str, float]]:
        """Demote a fused candidate that another fused candidate supersedes.

        Applied to the full ranking BEFORE any top-k cut, so a stale hit is
        demoted whenever its replacement is a candidate at all — not only
        when the replacement also survives the cut (the old
        inside-the-window rule made the repair vanish exactly at the small k
        where stale leads hurt most). The superseded candidate loses gamma
        of its score; the ranking re-sorts once. Inert at gamma = 1.
        """
        gamma = self._config.supersession_gamma
        if gamma >= 1.0 or self._graph is None:
            return ranked
        candidate_ids = {rid for rid, _ in ranked}
        adjusted: list[tuple[str, float]] = []
        for rid, score in ranked:
            superseding = self._graph.supersedes.get(rid)
            if superseding is not None and superseding in candidate_ids:
                adjusted.append((rid, score * gamma))
            else:
                adjusted.append((rid, score))
        return sorted(adjusted, key=lambda pair: (-pair[1], pair[0]))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def score_result(result: RetrievalResult, query: Query, k: int) -> dict[str, float]:
    """Recall/precision, evidence sufficiency, provenance, stale-hit rate.

    - ``recall``    — |returned ∩ relevant| / |relevant|; 0.0 for an empty
      ground truth (a query with no relevant evidence cannot raise recall).
    - ``precision`` — |returned ∩ relevant| / |returned|.
    - ``sufficiency`` — 1.0 iff *every* relevant record is returned: the
      deterministic stand-in for answer/task quality (a generator cannot
      answer correctly from context lacking the evidence). A necessary, not
      sufficient, condition — reported as such.
    - ``provenance_completeness`` — share of returned hits whose chain is
      intact: expanded hits must cite a real source and non-empty entity
      (direct vector hits need no chain). Expansion is decided by the hit's
      admission-time origin, not by chain presence, so a hit whose chain was
      lost is measured as the defect it is instead of being reclassified as
      direct. Catches truncation/dedup bugs that orphan evidence from its
      justification.
    - ``provenance_self_containment`` — share of *expanded* hits whose
      citing source is also inside the returned window. Below 1.0 means
      fusion admitted records whose justification fell outside the cut —
      the context is not self-justifying without a second retrieval. This
      is a real, measured defect mode of unbounded fusion, not a harness
      bug; see the seeded at-scale test.
    - ``stale_hit_rate`` — 1.0 iff the *lead* returned record is one of the
      query's known-stale records: answering with a superseded fact.
    """
    returned = list(result.ids[:k])
    returned_set = set(returned)
    relevant = set(query.relevant)
    recall = len(returned_set & relevant) / len(relevant) if relevant else 0.0
    precision = len(returned_set & relevant) / len(returned) if returned else 0.0
    sufficiency = 1.0 if relevant and relevant <= returned_set else 0.0

    checked = 0
    complete = 0
    expanded_total = 0
    self_contained = 0
    for hit in result.hits[:k]:
        checked += 1
        if not hit.is_expanded:
            complete += 1  # a direct vector hit needs no chain
            continue
        expanded_total += 1
        chain_ok = bool(hit.provenance) and all(
            bool(step.via_entity) and bool(step.from_memory) for step in hit.provenance
        )
        if chain_ok:
            complete += 1
        if chain_ok and all(
            step.from_memory in returned_set or step.from_memory == hit.memory_id
            for step in hit.provenance
        ):
            self_contained += 1
    completeness = complete / checked if checked else 0.0
    containment = self_contained / expanded_total if expanded_total else 1.0

    stale_lead = 0.0
    if query.stale and returned:
        stale_lead = 1.0 if returned[0] in set(query.stale) else 0.0

    return {
        "recall": recall,
        "precision": precision,
        "sufficiency": sufficiency,
        "provenance_completeness": completeness,
        "provenance_self_containment": containment,
        "stale_hit_rate": stale_lead,
        "expanded_hits": float(sum(1 for h in result.hits[:k] if h.is_expanded)),
    }


def _p95(values: list[int]) -> float:
    """Nearest-rank 95th percentile: no interpolation can move the number."""
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return float(ordered[rank - 1])


def evaluate_strategy(
    retriever: WorkspaceRetriever,
    strategy_name: str,
    k: int,
    queries: tuple[Query, ...] | None = None,
) -> dict[str, float]:
    """Run one strategy over the query set; aggregate mean metrics + p95 work.

    Aggregation is a plain mean over queries plus the nearest-rank p95 of
    per-query work units — deterministic and order-stable.
    """
    selected = queries if queries is not None else retriever.history.queries
    if not selected:
        raise ValueError("no queries to evaluate")
    per_query: list[dict[str, float]] = []
    works: list[int] = []
    for query in selected:
        result = retriever.run(strategy_name, query, k)
        metrics = score_result(result, query, k)
        metrics["work_units"] = float(result.work_units)
        metrics["expansion_admissions"] = float(result.expansion_admissions)
        metrics["expansion_inspected"] = float(result.expansion_inspected)
        per_query.append(metrics)
        works.append(result.work_units)

    summary: dict[str, float] = {}
    for key in per_query[0]:
        summary[key] = sum(m[key] for m in per_query) / len(per_query)
    summary["p95_work_units"] = _p95(works)
    summary["queries"] = float(len(per_query))
    return summary


def storage_cost(history: WorkspaceHistory, graph: ExtractedGraph, dim: int) -> dict[str, float]:
    """Deterministic index/storage accounting, in units and stated bounds.

    Vector-only storage is N records  x  dim floats (8 bytes each). The graph
    adds entity nodes, membership edges, dependency edges and supersession
    entries — the added complexity whose justification the hypothesis is
    about, priced in the same units. Bytes are stated per-unit bounds (one
    float per vector component; one 8-byte reference per membership edge,
    three per dependency edge, 16 per entity node, 16 per supersession
    entry — a stale/current id pair), not allocator truth. Supersession
    entries are part of the projection's index surface — the harness
    reports their count separately AND prices them, so a temporal corpus
    does not get its graph cost subsidized to zero.
    """
    memberships = sum(len(ids) for ids in graph.memberships.values())
    entities = len(graph.memberships)
    return {
        "records": float(len(history.records)),
        "vector_floats": float(len(history.records) * dim),
        "vector_bytes": float(len(history.records) * dim * 8),
        "entity_nodes": float(entities),
        "membership_edges": float(memberships),
        "dependency_edges": float(len(graph.dependencies)),
        "supersession_entries": float(len(graph.supersedes)),
        "graph_bytes": float(
            memberships * 8
            + 3 * 8 * len(graph.dependencies)
            + 16 * len(graph.supersedes)
            + entities * 16
        ),
    }


# ---------------------------------------------------------------------------
# Hand-checked fixture — explicit vectors, arithmetic in the comments
# ---------------------------------------------------------------------------

#: Five orthogonal concept axes (a: auth, b: billing, r: report, p: postgres,
#: c: plants). Every fixture vector is a normalized combination, so cosines
#: are hand-computable: with A, B, R, P, C orthonormal,
#:
#:     m1 = A   m2 = (A+B)/√2   m3 = (B+R)/√2   m4 = C   m5 = m6 = (A+P)/√2
#:
#: and any query dot product is a sum of ±1/√2, 1/√10, or 0 terms. The point
#: of the table is that no hash collision can move these numbers.
_A = (1.0, 0.0, 0.0, 0.0, 0.0)
_B = (0.0, 1.0, 0.0, 0.0, 0.0)
_R = (0.0, 0.0, 1.0, 0.0, 0.0)
_P = (0.0, 0.0, 0.0, 1.0, 0.0)
_C = (0.0, 0.0, 0.0, 0.0, 1.0)
_AB = _unit((1.0, 1.0, 0.0, 0.0, 0.0))  # (1/√2, 1/√2, 0, 0, 0)
_BR = _unit((0.0, 1.0, 1.0, 0.0, 0.0))
_AP = _unit((1.0, 0.0, 0.0, 1.0, 0.0))  # (1/√2, 0, 0, 1/√2, 0)

_HAND_TABLE = {
    "auth uses vector search": _A,
    "billing consumes auth tokens": _AB,
    "report renders billing totals": _BR,
    "office plants need water": _C,
    "auth runs postgres 12": _AP,
    "auth upgraded to postgres 18": _AP,
    "auth": _A,
    "what breaks if auth changes": _A,
    "which postgres does auth run": _P,
}


def hand_checked_history() -> WorkspaceHistory:
    """Six records, three queries, every expected number derivable by hand.

    Structure:

    - ``billing`` depends on ``auth``; ``report`` depends on ``billing`` —
      the dependency chain the relational query traverses;
    - two temporal facts about auth/postgres with the *identical* content
      vector (m5 stale at day 2, m6 current at day 10, m6 supersedes m5) —
      pure similarity cannot separate them: cos(q, m5) = cos(q, m6) = 1/√2
      exactly for the temporal query;
    - one distractor record sharing no concept axis with any query.

    Queries and ground truth (frozen by construction):

    - ``q_direct`` "auth" → relevant {m1, m2}: the records that concern
      auth's design. Vector-only must ace this; the test family pins what
      hybrid anchoring *costs* here (see the pollution test).
    - ``q_relational`` "what breaks if auth changes" → relevant {m2, m3}:
      the impact chain. m3's vector is orthogonal to the query's (m3 = BR,
      query = A, dot = 0 exactly), so vector-only cannot rank it at any k;
      one anchored hop from m1/m2 over the billing→auth edge admits it.
    - ``q_temporal`` "which postgres does auth run" → relevant {m6}, stale
      {m5}: the current fact must lead; the superseded one must not.
    """
    records = (
        MemoryRecord(
            memory_id="m1",
            text="auth uses vector search",
            day=1,
            entities=frozenset({"auth"}),
            project="atlas",
            kind="fact",
            weight=0.5,
        ),
        MemoryRecord(
            memory_id="m2",
            text="billing consumes auth tokens",
            day=2,
            entities=frozenset({"billing", "auth"}),
            project="atlas",
            kind="decision",
            weight=0.8,
        ),
        MemoryRecord(
            memory_id="m3",
            text="report renders billing totals",
            day=3,
            entities=frozenset({"report", "billing"}),
            project="atlas",
            kind="decision",
            weight=0.8,
        ),
        MemoryRecord(
            memory_id="m4",
            text="office plants need water",
            day=4,
            entities=frozenset(),
            project=None,
            kind="fact",
            weight=0.3,
        ),
        MemoryRecord(
            memory_id="m5",
            text="auth runs postgres 12",
            day=2,
            entities=frozenset({"auth"}),
            project="atlas",
            kind="fact",
            weight=0.5,
        ),
        MemoryRecord(
            memory_id="m6",
            text="auth upgraded to postgres 18",
            day=10,
            entities=frozenset({"auth"}),
            project="atlas",
            kind="fact",
            weight=0.5,
        ),
    )
    dependencies = (
        Dependency("billing", "auth", 2),
        Dependency("report", "billing", 3),
    )
    supersessions = (Supersession("m6", "m5", 10),)
    queries = (
        Query("q_direct", "auth", "direct", frozenset({"m1", "m2"})),
        Query(
            "q_relational",
            "what breaks if auth changes",
            "relational",
            frozenset({"m2", "m3"}),
        ),
        Query(
            "q_temporal",
            "which postgres does auth run",
            "temporal",
            frozenset({"m6"}),
            frozenset({"m5"}),
        ),
    )
    return WorkspaceHistory(
        workspace_id="ws-hand",
        records=records,
        dependencies=dependencies,
        supersessions=supersessions,
        queries=queries,
        now_day=10,
    )


# ---------------------------------------------------------------------------
# Seeded corpus — generated structure with construction-guaranteed properties
# ---------------------------------------------------------------------------

#: Deterministic vocabulary for the seeded corpus. Entity names are compound
#: words sharing no token with each other, so the hashed embedder cannot leak
#: similarity across entities: any cross-entity vector match is a shared
#: common word, and the relational ground truth is built so the next-hop
#: record shares *no* token with its query — checked textually at build time,
#: because the whole comparison rides on that property.
_SEED_ENTITIES = (
    "authgate",
    "budgetbeacon",
    "crawlkit",
    "graphitefinch",
    "ledgersvc",
    "notifyhound",
)


def seeded_history(seed: int, *, chain_length: int = 6, days: int = 60) -> WorkspaceHistory:
    """A generated Workspace history: dependency chain, projects, temporal pairs.

    Construction guarantees, which is what the seeded assertions rely on:

    - entities form a dependency chain E0 ← E1 ← … ← E(n-1) (Ei depends on
      E(i-1));
    - each entity Ei (i ≥ 1) has: a design fact, a consumer decision naming
      Ei and E(i-1), and a temporal fact pair (stale fact superseded by the
      current one); E0 has only its design fact;
    - *direct* query "Ei" counts exactly Ei's own records — any record
      naming another entity shares no token with the query;
    - *relational* query "what breaks if E(i) changes" counts the
      CONSUMPTION STATEMENTS along the impact chain — E(i)'s dependent's
      consumer decision ("E(i+1) consumes E(i) ..."), plus the next hop's
      ("E(i+2) consumes E(i+1) ...") when it exists. Relevance is labeled
      from the record template's ROLE (its fixed id suffix), never from the
      entity-membership predicate the hybrid strategy expands through —
      otherwise the headline comparison could not lose: hybrid would
      "recall" whatever it expanded into by definition. The dependent's
      design fact and temporal pair are deliberately NOT relevant: they name
      E(i+1) but answer nothing about what breaks. The next-hop statement
      shares no token with the query (asserted textually below), so
      vector-only retrieval cannot rank it; one query-anchored hop from any
      E(i)-mentioning candidate reaches it iff the E(i+1)→E(i) edge survived
      extraction;
    - *temporal* queries ask after "Ei provisioning", where the stale and
      current facts score identically (same token counts) — the lead is
      decided by tie-break alone, i.e. by recency/supersession machinery.
    """
    if chain_length < 2:
        raise ValueError("chain_length must be >= 2")
    if chain_length > len(_SEED_ENTITIES):
        raise ValueError("chain_length exceeds the fixed entity vocabulary")
    entities = _SEED_ENTITIES[:chain_length]
    records, dependencies, supersessions = _seeded_records(entities, days)
    queries = _seeded_queries(entities, records, chain_length)
    history = WorkspaceHistory(
        workspace_id=f"ws-seed-{seed}",
        records=tuple(records),
        dependencies=tuple(dependencies),
        supersessions=tuple(supersessions),
        queries=tuple(queries),
        now_day=days,
    )
    _validate_history(history)
    _assert_relational_invisibility(history, entities, chain_length)
    return history


def _seeded_records(
    entities: tuple[str, ...], days: int
) -> tuple[list[MemoryRecord], list[Dependency], list[Supersession]]:
    """The chain template: per-entity design fact, consumer decision, temporal pair."""
    projects = ("atlas", "beacon")
    records: list[MemoryRecord] = []
    dependencies: list[Dependency] = []
    supersessions: list[Supersession] = []

    def _add(memory_id: str, text: str, day: int, ents: tuple[str, ...], kind: str) -> None:
        records.append(
            MemoryRecord(
                memory_id=memory_id,
                text=text,
                day=day,
                entities=frozenset(ents),
                project=projects[entities.index(ents[0]) % 2],
                kind=kind,
                weight=0.8 if kind == "decision" else 0.5,
            )
        )

    for index, entity in enumerate(entities):
        day = 1 + (index * 3) % (days // 2)
        _add(
            f"{entity}-design",
            f"{entity} stores its state in the design record {index}",
            day,
            (entity,),
            "fact",
        )
        if index == 0:
            continue
        provider = entities[index - 1]
        _add(
            f"{entity}-consumes",
            f"{entity} consumes {provider} for every request path",
            day + 1,
            (entity, provider),
            "decision",
        )
        dependencies.append(Dependency(entity, provider, day + 1))
        _add(f"{entity}-v1-stale", f"{entity} was provisioned small", day + 2, (entity,), "fact")
        current_day = day + 3 + (index % 5)
        _add(
            f"{entity}-v2-current",
            f"{entity} was provisioned large",
            current_day,
            (entity,),
            "fact",
        )
        supersessions.append(
            Supersession(f"{entity}-v2-current", f"{entity}-v1-stale", current_day)
        )
    return records, dependencies, supersessions


def _seeded_queries(
    entities: tuple[str, ...], records: list[MemoryRecord], chain_length: int
) -> list[Query]:
    """Direct, relational, and temporal queries over the finished corpus.

    Relational relevance is labeled from record ROLE (the fixed
    ``<entity>-consumes`` template ids along the impact chain), independent
    of the membership predicate any strategy expands through.
    """
    queries: list[Query] = []
    for index, entity in enumerate(entities):
        if index == 0:
            continue
        # Direct ground truth includes the stale twin on purpose: "tell me
        # about E" is answered by everything about E. The stale-lead axis is
        # the temporal queries' job — the validator forbids a record being
        # both relevant and stale on one query.
        queries.append(
            Query(
                query_id=f"direct-{entity}",
                text=entity,
                family="direct",
                relevant=frozenset(
                    r.memory_id
                    for r in records
                    if entity in r.entities and r.memory_id.startswith(entity)
                ),
            )
        )
        if index + 1 < chain_length:
            # Impact-chain consumption statements: the dependent's own
            # consumer decision, plus the next hop's when the chain
            # continues. Role-labeled, not membership-labeled — see the
            # seeded_history docstring.
            relevant = {f"{entities[index + 1]}-consumes"}
            if index + 2 < chain_length:
                relevant.add(f"{entities[index + 2]}-consumes")
            queries.append(
                Query(
                    query_id=f"relational-{entity}",
                    text=f"what breaks if {entity} changes",
                    family="relational",
                    relevant=frozenset(relevant),
                )
            )
        queries.append(
            Query(
                query_id=f"temporal-{entity}",
                text=f"{entity} provisioning",
                family="temporal",
                relevant=frozenset({f"{entity}-v2-current"}),
                stale=frozenset({f"{entity}-v1-stale"}),
            )
        )
    return queries


def _assert_relational_invisibility(
    history: WorkspaceHistory, entities: tuple[str, ...], chain_length: int
) -> None:
    """The property the whole comparison rides on, checked textually.

    The next-hop record of a relational query (E(i+2)'s consumer decision,
    which mentions only E(i+2) and E(i+1)) must not mention the queried
    entity E(i) — else vector-only could rank it and the "graph finds what
    similarity cannot" claim would be false.
    """
    for query in history.queries:
        if query.family != "relational":
            continue
        subject = query.query_id.removeprefix("relational-")
        index = entities.index(subject)
        if index + 2 >= chain_length:
            continue
        next_hop = next(
            r for r in history.records if r.memory_id == f"{entities[index + 2]}-consumes"
        )
        if subject in HashEmbedder.tokens(next_hop.text):
            raise ValueError(
                f"fixture construction broken: {next_hop.memory_id} mentions {subject}"
            )
    return history


# ===========================================================================
# Tests
# ===========================================================================


class TestEvidenceOnlyContract:
    """The harness may be evidence, never an authority (epic contract)."""

    def test_advisory_marker_is_true(self) -> None:
        assert ADVISORY_ONLY is True

    def test_module_imports_no_maistro_module(self) -> None:
        """AST scan: no ``import maistro*`` anywhere in this file.

        The issue's one hard prohibition is creating a second canonical
        memory store. An evidence harness that imports the memory package
        could drift into calling it; one that cannot import it cannot.
        """
        tree = ast.parse(module_source())
        banned: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("maistro"):
                        banned.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("maistro"):
                    banned.append(module)
        assert banned == []

    def test_results_are_frozen(self) -> None:
        """Measurements cannot be mutated into authorization after the fact."""
        history = hand_checked_history()
        retriever = WorkspaceRetriever(
            history,
            TableEmbedder(_HAND_TABLE),
            extract_graph(history, ExtractionErrorRates(), seed=0),
        )
        result = retriever.vector_only(history.queries[0], 2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.hits = ()  # type: ignore[misc]

    def test_empty_corpus_rejected(self) -> None:
        history = hand_checked_history()
        empty = WorkspaceHistory(
            workspace_id="ws-empty",
            records=(),
            dependencies=(),
            supersessions=(),
            queries=history.queries,
            now_day=10,
        )
        with pytest.raises(ValueError, match="empty corpus"):
            WorkspaceRetriever(empty, TableEmbedder(_HAND_TABLE))

    def test_bad_configs_rejected(self) -> None:
        with pytest.raises(ValueError, match="candidate_pool"):
            StrategyConfig(candidate_pool=-1)
        with pytest.raises(ValueError, match="expansion_budget"):
            StrategyConfig(expansion_budget=-1)
        with pytest.raises(ValueError, match="supersession_gamma"):
            StrategyConfig(supersession_gamma=1.5)
        with pytest.raises(ValueError, match="recency_half_life"):
            StrategyConfig(recency_half_life=0.0)
        with pytest.raises(ValueError, match="expansion_weight"):
            StrategyConfig(expansion_weight=-0.1)

    def test_invalid_extraction_rates_rejected(self) -> None:
        with pytest.raises(ValueError, match="edge_miss"):
            ExtractionErrorRates(edge_miss=1.5)
        with pytest.raises(ValueError, match="mention_drop"):
            ExtractionErrorRates(mention_drop=-0.1)

    def test_inconsistent_history_rejected(self) -> None:
        history = hand_checked_history()
        ghost = (Query("q_ghost", "auth", "direct", frozenset({"no-such-record"})),)
        broken = WorkspaceHistory(
            workspace_id="ws-broken",
            records=history.records,
            dependencies=history.dependencies,
            supersessions=history.supersessions,
            queries=ghost,
            now_day=10,
        )
        with pytest.raises(ValueError, match="not in corpus"):
            WorkspaceRetriever(broken, TableEmbedder(_HAND_TABLE))

    def test_duplicate_query_ids_rejected(self) -> None:
        """Two queries sharing an id would poison the per-id vector cache.

        The retriever caches query embeddings keyed by ``query_id``; a
        duplicate silently overwrites the first query's vector and both are
        then scored against the last one's — plausible recall numbers from a
        broken query set, nothing raising. Rejected at validation instead.
        """
        history = hand_checked_history()
        duplicated = (
            *history.queries,
            Query("q_direct", "a different text, same id", "direct", frozenset({"m4"})),
        )
        broken = WorkspaceHistory(
            workspace_id="ws-dup-query",
            records=history.records,
            dependencies=history.dependencies,
            supersessions=history.supersessions,
            queries=duplicated,
            now_day=10,
        )
        with pytest.raises(ValueError, match="duplicate query ids"):
            WorkspaceRetriever(broken, TableEmbedder(_HAND_TABLE))

    def test_unknown_dependency_endpoint_rejected(self) -> None:
        """A dependency naming an entity no record mentions is refused.

        Such an edge has no membership node, so traversal could never use
        it, but ``graph_construction_error`` would still count it as ground
        truth — silently corrupting both the recall and construction-error
        numbers. Accepted-typo ground truth is fake evidence.
        """
        history = hand_checked_history()
        broken = WorkspaceHistory(
            workspace_id="ws-ghost-dep",
            records=history.records,
            dependencies=(*history.dependencies, Dependency("auth", "nosuchent", 4)),
            supersessions=history.supersessions,
            queries=history.queries,
            now_day=10,
        )
        with pytest.raises(ValueError, match="entities no record mentions"):
            WorkspaceRetriever(broken, TableEmbedder(_HAND_TABLE))

    def test_unknown_strategy_rejected(self) -> None:
        history = hand_checked_history()
        retriever = WorkspaceRetriever(history, TableEmbedder(_HAND_TABLE))
        with pytest.raises(ValueError, match="unknown strategy"):
            retriever.run("graph_only", history.queries[0], 3)


def module_source() -> str:
    """This module's own source, for the no-maistro-import contract check."""
    return Path(__file__).read_text(encoding="utf-8")


class TestHandCheckedArithmetic:
    """Every number here is checkable by hand against the declared vectors.

    Concept axes are orthonormal 5-dim vectors, so every cosine reduces to
    sums of 1/√2 ≈ 0.70711 factors. m1 = A; m2 = AB; m3 = BR; m4 = C;
    m5 = m6 = AP.
    """

    @staticmethod
    def _retriever(
        rates: ExtractionErrorRates | None = None, config: StrategyConfig | None = None
    ) -> WorkspaceRetriever:
        history = hand_checked_history()
        graph = extract_graph(history, rates or ExtractionErrorRates(), seed=0)
        return WorkspaceRetriever(history, TableEmbedder(_HAND_TABLE), graph, config)

    def test_cosine_basics(self) -> None:
        assert cosine(_A, _A) == pytest.approx(1.0)
        assert cosine(_A, _B) == pytest.approx(0.0, abs=1e-12)
        assert cosine(_AP, _P) == pytest.approx(1 / math.sqrt(2))
        assert cosine((0.0, 0.0), (1.0, 0.0)) == 0.0  # zero vector: 0.0, never NaN
        with pytest.raises(ValueError, match="dimension mismatch"):
            cosine(_A, _B[:2])

    def test_vector_only_direct_family_is_aced(self) -> None:
        """q_direct, query = A: cosines m1=1.0; m2=m5=m6=1/√2; m3=m4=0.

        Id tiebreak orders the 1/√2 band m2 < m5 < m6, so top-2 = {m1, m2}
        = ground truth: recall 1.0, precision 1.0. The sanity family —
        plain factual recall is the thing any strategy must start from.
        """
        retriever = self._retriever()
        query = retriever.history.queries[0]
        assert query.query_id == "q_direct"
        result = retriever.vector_only(query, 2)
        assert result.ids == ("m1", "m2")
        metrics = score_result(result, query, 2)
        assert metrics["recall"] == 1.0
        assert metrics["precision"] == 1.0
        assert metrics["sufficiency"] == 1.0

    def test_vector_only_cannot_rank_multihop_evidence(self) -> None:
        """q_relational, query = A: m3 = BR has dot 0 with the query.

        m3 can never be a *positive* vector hit — structurally, at any k.
        Top-4 is m1(1.0) then the 1/√2 band m2, m5, m6: relevant = {m2, m3}
        catches only m2, so recall is exactly 1/2 and sufficiency 0 — the
        gap the graph hop exists to close. (m3 IS returned by the baseline
        at deeper ranks, as ``find_similar``'s LIMIT returns it — with score
        0.0 and no chance of outranking a positive hit.)
        """
        retriever = self._retriever()
        query = retriever.history.queries[1]
        assert query.query_id == "q_relational"
        result = retriever.vector_only(query, 4)
        assert "m3" not in result.ids
        assert result.ids == ("m1", "m2", "m5", "m6")
        metrics = score_result(result, query, 4)
        assert metrics["recall"] == pytest.approx(0.5)
        assert metrics["sufficiency"] == 0.0

    def test_vector_only_keeps_zero_similarity_rows_like_the_seam(self) -> None:
        """The baseline returns orthogonal rows inside the window, as the seam does.

        ``find_similar`` orders by cosine distance and LIMITs — no
        positive-similarity predicate — so at k=6 the hand fixture returns
        the four positive hits AND the two orthogonal records (m3, m4) with
        score 0.0. This is not cosmetic: q_relational's ground truth names
        m3, so the seam-parity window recalls it (1.0) where a
        positive-only window declares structurally-reachable evidence
        unreachable (0.5 at k=4). Dropping zero rows flatters the baseline's
        measured loss and breaks equivalence with the seam this strategy
        stands in for.
        """
        retriever = self._retriever()
        query = retriever.history.queries[1]
        assert retriever.vector_only(query, 4).ids == ("m1", "m2", "m5", "m6")
        result = retriever.vector_only(query, 6)
        assert result.ids == ("m1", "m2", "m5", "m6", "m3", "m4")
        assert [hit.score for hit in result.hits[-2:]] == [0.0, 0.0]
        # The zero-similarity row IS relevant ground truth inside the window:
        # the seam-parity baseline recalls it, at 0.0 score.
        assert score_result(result, query, 6)["recall"] == pytest.approx(1.0)
        assert score_result(result, query, 4)["recall"] == pytest.approx(0.5)

    def test_hybrid_reaches_multihop_evidence_within_default_budget(self) -> None:
        """Anchored hop from m1 over billing admits m3; fusion ranks it first.

        Anchor set of q_relational = {auth}. Candidate m1 (score 1.0):
        neighbors of auth = {billing} (billing→auth edge) → memberships
        (billing) = {m2 (pool), m3} → m3 admitted fused 1.25  x  1.0 = 1.25.
        Candidate m2 (1/√2) reaches m3 too but the better path wins.
        Ranking: m3(1.25), m1(1.0), then the 1/√2 band m2, m5, m6 → top-3
        = {m3, m1, m2} ⊇ {m2, m3}: recall 1.0, sufficiency 1.0, precision
        2/3 — at the same k=3 where vector-only sufficiency was 0.
        """
        retriever = self._retriever()
        query = retriever.history.queries[1]
        result = retriever.hybrid(query, 3)
        assert set(result.ids[:3]) >= {"m2", "m3"}
        metrics = score_result(result, query, 3)
        assert metrics["recall"] == 1.0
        assert metrics["sufficiency"] == 1.0
        assert metrics["precision"] == pytest.approx(2 / 3)
        by_id = {hit.memory_id: hit for hit in result.hits}
        assert by_id["m1"].provenance == ()  # pool hit, no chain needed
        assert by_id["m3"].is_expanded
        assert by_id["m3"].provenance == (
            ProvenanceStep(from_memory="m1", via_entity="billing", relation="dependency"),
        )

    def test_expanded_hit_provenance_is_exact(self) -> None:
        """The chain names the candidate, entity, and relation — all of it —
        and provenance completeness over the returned context is 1.0."""
        retriever = self._retriever()
        query = retriever.history.queries[1]
        result = retriever.hybrid(query, 5)
        expanded = [h for h in result.hits if h.is_expanded]
        assert len(expanded) == 1
        step = expanded[0].provenance[0]
        assert step.from_memory == "m1"
        assert step.via_entity == "billing"
        assert step.relation == "dependency"
        metrics = score_result(result, query, 5)
        assert metrics["provenance_completeness"] == 1.0

    def test_zero_budget_degenerates_exactly_to_vector_only(self) -> None:
        """beta, gamma, and the graph must be inert at budget 0: identical rankings.

        This is the pin that keeps "hybrid" honest — with expansion off it
        is its baseline, nothing more.
        """
        history = hand_checked_history()
        degenerate = self._retriever(
            config=StrategyConfig(expansion_budget=0, supersession_gamma=1.0)
        )
        plain = self._retriever()
        for query in history.queries:
            assert degenerate.hybrid(query, 3).ids == plain.vector_only(query, 3).ids, (
                f"budget-0 hybrid diverged on {query.query_id}"
            )

    def test_recall_monotone_in_expansion_budget(self) -> None:
        """More budget never loses the relevant set: {0 → 1 → 2 → 4}.

        Budget 0 admits nothing (recall 0.5); budget 1 admits m3 from m1
        (recall 1.0); more budget cannot drop it — expansion only adds
        candidates to the fusion map, never removes or rescores a pool hit.
        """
        query = hand_checked_history().queries[1]
        recalls = []
        for budget in (0, 1, 2, 4):
            retriever = self._retriever(config=StrategyConfig(expansion_budget=budget))
            recalls.append(score_result(retriever.hybrid(query, 3), query, 3)["recall"])
        assert recalls == [0.5, 1.0, 1.0, 1.0]
        assert recalls == sorted(recalls)

    def test_vector_only_leads_with_the_stale_fact(self) -> None:
        """q_temporal, query = P: cos(q, m5) = cos(q, m6) = 1/√2 exactly.

        m5 = m6 = AP — similarity cannot separate them, and the id tiebreak
        (m5 < m6) hands the lead to the *superseded* fact. This is the
        failure the graph's supersession edge exists to repair.
        """
        retriever = self._retriever()
        query = retriever.history.queries[2]
        assert query.query_id == "q_temporal"
        result = retriever.vector_only(query, 2)
        assert result.ids == ("m5", "m6")
        metrics = score_result(result, query, 1)
        assert metrics["stale_hit_rate"] == 1.0

    def test_recency_weighting_fixes_the_single_stale_pair(self) -> None:
        """Cosine  x  weight  x  recency: m6 (day 10) outranks m5 (day 2).

        The honest control for the demotion test — and a HYPOTHETICAL one:
        the shipped indexed vector seam scores max(cosine, 0) x weight with
        no recency term (``memory/working/indexed.py``), so this strategy is
        what a recency column WOULD buy, not what the current policy does.
        Recency is exactly what separates the pair. Equal weights (0.5)
        cancel, so s(m5) = (1/√2)·(1/(1+8/30)) ≈ 0.558·(1/√2) < s(m6) = 1/√2.
        """
        retriever = self._retriever()
        query = retriever.history.queries[2]
        result = retriever.vector_recency(query, 2)
        assert result.ids[0] == "m6"
        metrics = score_result(result, query, 1)
        assert metrics["stale_hit_rate"] == 0.0

    def test_supersession_demotion_fixes_stale_lead_without_recency(self) -> None:
        """The graph edge repairs the lead where the score is recency-blind.

        Budget 0 isolates the mechanism (no expansion noise). gamma = 0.25:
        m5's 1/√2 becomes (1/√2)·0.25 because m6 is a fused candidate, so
        m6 leads on fused score alone — and the demotion runs over the FULL
        candidate set BEFORE the top-k cut, so the repair holds at k=1 too:
        the old inside-the-window rule left m5 leading whenever its
        replacement sat one slot outside the cut, i.e. exactly at the small
        windows stale-lead questions ask with. The mechanism is available to
        seams that have no recency column in their score at all — the
        durable similarity path orders purely by cosine distance.
        """
        retriever = self._retriever(
            config=StrategyConfig(supersession_gamma=0.25, expansion_budget=0)
        )
        query = retriever.history.queries[2]
        assert retriever.hybrid(query, 1).ids == ("m6",)
        result = retriever.hybrid(query, 2)
        assert result.ids[0] == "m6"
        assert result.hits[0].score == pytest.approx(1 / math.sqrt(2))
        assert result.hits[1].score == pytest.approx(0.25 / math.sqrt(2))
        metrics = score_result(result, query, 1)
        assert metrics["stale_hit_rate"] == 0.0
        metrics = score_result(result, query, 2)
        assert metrics["stale_hit_rate"] == 0.0

    def test_hybrid_anchoring_costs_the_direct_family(self) -> None:
        """The tradeoff, hand-checked: anchoring pollutes simple queries.

        q_direct, budget 6: from m1 (anchor auth) the billing→auth edge
        pulls billing's memberships — m3 fused 1.25 — so the top-2 becomes
        {m3, m1} and ground-truth member m2 (1/√2) falls out: recall drops
        1.0 → 0.5 against vector-only at the same k. The relational gain
        and the direct loss are the same mechanism; that is the finding the
        disposition turns on, not a bug to hide.
        """
        retriever = self._retriever()
        query = retriever.history.queries[0]
        vector_metrics = score_result(retriever.vector_only(query, 2), query, 2)
        hybrid_metrics = score_result(retriever.hybrid(query, 2), query, 2)
        assert vector_metrics["recall"] == 1.0
        assert hybrid_metrics["recall"] == pytest.approx(0.5)
        assert hybrid_metrics["recall"] < vector_metrics["recall"]
        assert "m3" in retriever.hybrid(query, 2).ids[:2]

    def test_incorrect_edge_admits_a_distractor_and_loses_the_hop(self) -> None:
        """Sensitivity to incorrect edges, constructively hand-checked.

        Corrupt the graph with a false "plants depends on auth" edge (the
        extractor also linked plants' records, as real wrong edges point at
        real, populated entities; billing→auth is removed). Anchored
        expansion from m1 now follows the false edge into plants and admits
        m4 fused 1.25, while m3 is unreachable (no true edge into auth):
        top-3 = {m4, m1, m2}. The corrupted graph is not merely no better
        than vector-only — the answer context now leads with watering
        plants.
        """
        history = hand_checked_history()
        graph = extract_graph(history, ExtractionErrorRates(), seed=0)
        corrupted = dataclasses.replace(
            graph,
            memberships={**graph.memberships, "plants": frozenset({"m4"})},
            dependencies=frozenset({("plants", "auth")}),
            spurious_dependencies=frozenset({("plants", "auth")}),
        )
        retriever = WorkspaceRetriever(
            history, TableEmbedder(_HAND_TABLE), corrupted, StrategyConfig()
        )
        query = history.queries[1]
        result = retriever.hybrid(query, 3)
        metrics = score_result(result, query, 3)
        assert metrics["recall"] == pytest.approx(0.5)
        assert metrics["sufficiency"] == 0.0
        assert result.ids[0] == "m4", "wrong edge failed to admit the distractor"
        assert "m3" not in result.ids

    def test_graph_construction_error_is_measured_exactly(self) -> None:
        """Miss/spur rates against ground truth are exact set arithmetic.

        Hand case: drop one of two edges → miss 0.5; keep both plus one
        invented edge → spur 1/3 of the extracted set. A real extractor's
        output plugs into the same frozen-set comparison unchanged.
        """
        history = hand_checked_history()
        clean = extract_graph(history, ExtractionErrorRates(), seed=0)
        report = graph_construction_error(history, clean)
        assert report["edge_miss_rate"] == 0.0
        assert report["edge_spur_rate"] == 0.0
        assert report["correct_edges"] == report["true_edges"] == 2.0

        truth = {(d.src, d.dst) for d in history.dependencies}
        halved = dataclasses.replace(clean, dependencies=frozenset(sorted(truth)[:1]))
        report = graph_construction_error(history, halved)
        assert report["edge_miss_rate"] == pytest.approx(0.5)

        invented = dataclasses.replace(
            clean,
            dependencies=frozenset(truth | {("report", "plants")}),
            spurious_dependencies=frozenset({("report", "plants")}),
        )
        report = graph_construction_error(history, invented)
        assert report["edge_spur_rate"] == pytest.approx(1 / 3)
        assert report["correct_edges"] == 2.0

    def test_total_extraction_failure_degenerates_to_vector_only(self) -> None:
        """At 100% edge miss the hybrid has nothing to expand through.

        The equality is the structural bound on the downside: a fully wrong
        graph costs the *difference*, never the baseline. Pins the floor of
        the "sensitivity to stale/incorrect edges" axis.
        """
        history = hand_checked_history()
        blind = extract_graph(history, ExtractionErrorRates(edge_miss=1.0), seed=3)
        assert blind.dependencies == frozenset()
        blind_retriever = WorkspaceRetriever(
            history, TableEmbedder(_HAND_TABLE), blind, StrategyConfig()
        )
        plain = self._retriever()
        for query in history.queries:
            assert blind_retriever.hybrid(query, 3).ids == plain.vector_only(query, 3).ids

    def test_storage_cost_accounting_is_exact(self) -> None:
        """Fixture storage: 6 vectors  x  5 floats; the graph adds its surcharge.

        Memberships: m1:1 + m2:2 + m3:2 + m4:0 + m5:1 + m6:1 = 7; graph
        bytes = memberships*8 + deps*24 + supersessions*16 + entities*16
        with the stated per-unit bounds — priced, not guessed, and the
        temporal corpus's supersession entry is IN the surcharge, not a
        free ride next to it.
        """
        history = hand_checked_history()
        graph = extract_graph(history, ExtractionErrorRates(), seed=0)
        cost = storage_cost(history, graph, dim=5)
        assert cost["records"] == 6.0
        assert cost["vector_floats"] == 30.0
        assert cost["vector_bytes"] == 240.0
        # Entity nodes: auth, billing, report — the distractor record m4 has
        # no entity mentions, and "plants" exists only as a reroute target.
        assert cost["entity_nodes"] == 3.0
        assert cost["membership_edges"] == 7.0
        assert cost["dependency_edges"] == 2.0
        assert cost["supersession_entries"] == 1.0
        assert cost["graph_bytes"] == 7 * 8 + 2 * 24 + 1 * 16 + 3 * 16
        #: The added complexity is real and, on this corpus, bounded by the
        #: vector cost it augments — the hypothesis must buy more than this.
        assert cost["graph_bytes"] < cost["vector_bytes"]

    def test_expansion_work_is_charged_exactly(self) -> None:
        """Hybrid work = vector work + admissions + inspections, exactly.

        Admissions are budget-capped; inspections (edges and membership
        entries enumerated, admitted or not) are not — the accounting
        charges both, so a latency claim cannot be certified by the budget
        alone.
        """
        history = hand_checked_history()
        graph = extract_graph(history, ExtractionErrorRates(), seed=0)
        config = StrategyConfig(expansion_budget=2)
        retriever = WorkspaceRetriever(history, TableEmbedder(_HAND_TABLE), graph, config)
        query = history.queries[1]
        result = retriever.hybrid(query, 3)
        vector_work = retriever.vector_only(query, 3).work_units
        assert result.expansion_admissions <= config.expansion_budget
        assert result.work_units == (
            vector_work + result.expansion_admissions + result.expansion_inspected
        )
        assert result.expansion_inspected > 0

    def test_latency_is_not_certified_by_the_budget(self) -> None:
        """A bigger membership surface costs real work even under one budget.

        The regression the admissions-only accounting hid: enlarging the
        traversed membership set (here: billing's membership grown to 40
        entries) leaves admissions capped at the budget while the scan
        enumerates every entry. The reported p95/work must move with that
        graph-size-dependent work — otherwise "latency bound = vector +
        budget" is true by construction and measures nothing.
        """
        history = hand_checked_history()
        graph = extract_graph(history, ExtractionErrorRates(), seed=0)
        config = StrategyConfig(expansion_budget=2)
        grown_members = frozenset({f"index-only-{i}" for i in range(40)}) | {"m2", "m3"}
        grown = dataclasses.replace(
            graph,
            memberships={**graph.memberships, "billing": grown_members},
        )
        plain = WorkspaceRetriever(history, TableEmbedder(_HAND_TABLE), graph, config)
        grown_retriever = WorkspaceRetriever(history, TableEmbedder(_HAND_TABLE), grown, config)
        query = history.queries[1]
        base = plain.hybrid(query, 3)
        measured = grown_retriever.hybrid(query, 3)
        # Admissions hit the same cap; the enumeration is what grew.
        assert measured.expansion_admissions == config.expansion_budget
        assert measured.expansion_inspected >= 40 + base.expansion_inspected
        vector_work = plain.vector_only(query, 3).work_units
        assert measured.work_units > vector_work + config.expansion_budget
        assert measured.work_units == (
            vector_work + measured.expansion_admissions + measured.expansion_inspected
        )

    def test_anchoring_uses_extracted_mentions_not_ground_truth(self) -> None:
        """A dropped mention breaks its record's anchor, as on the real seam.

        The extractor lost m1's ``auth`` mention: m1 must no longer anchor
        the expansion even though ground truth still says it mentions auth.
        m2 (whose extracted mentions survive) anchors instead, so m3 is
        admitted through the *worse* candidate — fused 1.25 x (1/√2) — and
        the provenance chain names m2. Reading ground-truth entities here
        would leak fixture truth into retrieval and understate
        mention-extraction failures.
        """
        history = hand_checked_history()
        graph = extract_graph(history, ExtractionErrorRates(), seed=0)
        dropped = dataclasses.replace(
            graph,
            memberships={**graph.memberships, "auth": frozenset({"m2", "m5", "m6"})},
        )
        retriever = WorkspaceRetriever(history, TableEmbedder(_HAND_TABLE), dropped)
        query = history.queries[1]
        result = retriever.hybrid(query, 3)
        assert "m3" in result.ids  # the hop still exists — through m2 only
        by_id = {hit.memory_id: hit for hit in result.hits}
        step = by_id["m3"].provenance[0]
        assert step.from_memory == "m2"
        assert step.from_memory != "m1", "anchoring read ground truth, not the extracted graph"
        assert by_id["m3"].score == pytest.approx(1.25 / math.sqrt(2))

    def test_expanded_origin_is_measured_independent_of_chain_integrity(self) -> None:
        """A chain-less expanded hit is a defect, not a reclassified direct hit.

        Expansion origin is fixed at admission; a hit whose provenance was
        lost (truncation/dedup bug) stays ``expanded`` with an empty chain,
        so completeness reports the defect instead of awarding the hit a
        free pass as a chain-free direct result.
        """
        query = hand_checked_history().queries[1]
        orphaned = RetrievalResult(
            hits=(
                Hit(memory_id="m1", score=1.0, origin="direct"),
                Hit(memory_id="m3", score=1.25, provenance=(), origin="expanded"),
            ),
            work_units=1,
            strategy="hybrid",
        )
        metrics = score_result(orphaned, query, 2)
        assert metrics["expanded_hits"] == 1.0
        assert metrics["provenance_completeness"] == pytest.approx(0.5)

    def test_evaluation_summary_is_stable_and_shaped(self) -> None:
        """The benchmark output: fixed metric keys, deterministic values."""
        history = hand_checked_history()
        graph = extract_graph(history, ExtractionErrorRates(), seed=0)
        retriever = WorkspaceRetriever(history, TableEmbedder(_HAND_TABLE), graph)
        summary = evaluate_strategy(retriever, "hybrid", 3)
        expected_keys = {
            "recall",
            "precision",
            "sufficiency",
            "provenance_completeness",
            "provenance_self_containment",
            "stale_hit_rate",
            "expanded_hits",
            "work_units",
            "expansion_admissions",
            "expansion_inspected",
            "p95_work_units",
            "queries",
        }
        assert set(summary) == expected_keys
        assert summary["queries"] == 3.0
        assert evaluate_strategy(retriever, "hybrid", 3) == summary


class TestSeededCorpus:
    """Generated structure — assertions construction guarantees, only."""

    @staticmethod
    def _built(
        seed: int, config: StrategyConfig | None = None
    ) -> tuple[WorkspaceHistory, ExtractedGraph, WorkspaceRetriever]:
        history = seeded_history(seed)
        graph = extract_graph(history, ExtractionErrorRates(), seed=seed)
        retriever = WorkspaceRetriever(history, HashEmbedder(dim=256), graph, config)
        return history, graph, retriever

    def test_corpus_shape_and_determinism(self) -> None:
        """Same seed, same corpus; the chain template fixes the counts.

        6 entities → E0 design + 5 x (design, consumes, stale, current) = 21
        records; 5 direct + 4 relational + 5 temporal = 14 queries.
        """
        first = seeded_history(11)
        second = seeded_history(11)
        assert first == second
        assert len(first.records) == 21
        assert len(first.dependencies) == 5
        assert len(first.supersessions) == 5
        families = [q.family for q in first.queries]
        assert families.count("direct") == 5
        # E5 has no dependent, so no relational query closes the chain.
        assert families.count("relational") == 4
        assert families.count("temporal") == 5
        assert len(first.queries) == 14
        other = seeded_history(12)
        assert other.workspace_id != first.workspace_id

    def test_relational_ground_truth_is_role_labeled(self) -> None:
        """Relational GT = the impact chain's consumption statements, by role.

        "What breaks if E(i) changes" is answered by E(i+1)'s consumer
        decision ("E(i+1) consumes E(i) ...") plus the next hop's ("E(i+2)
        consumes E(i+1) ...") when the chain continues. The labels come
        from the record template's fixed role ids — NOT from the
        entity-membership predicate the hybrid strategy expands through —
        and the dependent's design/temporal records, which membership alone
        would sweep in, are excluded: they name E(i+1) but answer nothing
        about what breaks. Without this independence, hybrid recall would
        equal its own expansion set by definition and the headline number
        would be a self-consistency check.
        """
        history = seeded_history(11)
        entities = _SEED_ENTITIES[:6]
        for query in history.queries:
            if query.family != "relational":
                continue
            subject = query.query_id.removeprefix("relational-")
            index = entities.index(subject)
            expected = {f"{entities[index + 1]}-consumes"}
            if index + 2 < len(entities):
                expected.add(f"{entities[index + 2]}-consumes")
            assert query.relevant == frozenset(expected)
            # Strictly narrower than the dependent's membership set: design
            # and temporal facts of E(i+1) are not impact evidence.
            membership = frozenset(
                r.memory_id for r in history.records if entities[index + 1] in r.entities
            )
            assert query.relevant < membership
            irrelevant = membership - query.relevant
            assert all(rid.endswith(("-design", "-v1-stale", "-v2-current")) for rid in irrelevant)
            #: ...and the next-hop record is invisible to the query — the
            #: property vector-only loses on.
            if index + 2 < len(entities):
                next_hop = next(
                    r for r in history.records if r.memory_id == f"{entities[index + 2]}-consumes"
                )
                assert subject not in next_hop.text
                assert subject not in HashEmbedder.tokens(next_hop.text)

    def test_vector_only_misses_relational_recall_hybrid_catches(self) -> None:
        """The seeded thesis check: hybrid relational recall > vector-only.

        The next-hop consumption statement shares no token with the query
        (asserted textually at build), the hashed embedder is exact
        per-token, and the clean graph holds the needed edge — so the one
        anchored hop is the only route to that evidence. Family means over
        the 4 relational queries at k=8, budget 6: vector-only catches only
        each chain's direct consumer decision (the one record sharing the
        queried entity's token) — recall 0.625, sufficiency 0.25 — while
        hybrid returns the whole impact chain (recall 1.0, sufficiency 1.0).
        The gap is real, not definitional: relevance is role-labeled, so a
        broken edge or a dropped mention now *can* lose the second-order
        record, which the stale-edge sweep below measures.
        """
        history, _graph, retriever = self._built(11)
        relational = tuple(q for q in history.queries if q.family == "relational")
        assert len(relational) == 4
        vector_summary = evaluate_strategy(retriever, "vector_only", 8, relational)
        hybrid_summary = evaluate_strategy(retriever, "hybrid", 8, relational)
        # Three queries catch 1 of 2 chain statements; the chain-end query
        # (no second hop exists) catches its only statement.
        assert vector_summary["recall"] == pytest.approx((3 * (1 / 2) + 1 / 1) / 4)
        assert vector_summary["sufficiency"] == pytest.approx(1 / 4)
        assert hybrid_summary["recall"] == pytest.approx(1.0)
        assert hybrid_summary["sufficiency"] == pytest.approx(1.0)
        assert hybrid_summary["expanded_hits"] > 0.0

    def test_hybrid_anchoring_costs_the_direct_family_at_scale(self) -> None:
        """The direct-family cost is structural, not a hand-fixture quirk.

        Anchored expansion follows the same edges for "E0" as for the
        relational question, so fused dependents' records displace E0's own
        low-similarity records from the top-k: family recall strictly
        below vector-only's. Measured, reported, and turned into the
        disposition's gating requirement — not smoothed over.
        """
        history, _graph, retriever = self._built(11)
        direct = tuple(q for q in history.queries if q.family == "direct")
        assert len(direct) == 5
        vector_summary = evaluate_strategy(retriever, "vector_only", 5, direct)
        hybrid_summary = evaluate_strategy(retriever, "hybrid", 5, direct)
        assert vector_summary["recall"] == pytest.approx(1.0)
        assert hybrid_summary["recall"] < vector_summary["recall"]

    def test_work_units_charge_traversal_per_query_on_seeded_corpus(self) -> None:
        """Admissions stay budget-capped per query; inspections are charged.

        The budget caps what fusion ADMITS, never what traversal ENUMERATES:
        per-query admissions ≤ budget, and hybrid work is exactly vector
        work + admissions + inspections — the breakdown that keeps the
        latency column honest about graph-size-dependent scanning.
        """
        retriever = self._built(11, config=StrategyConfig(expansion_budget=3))[2]
        for query in retriever.history.queries:
            result = retriever.hybrid(query, 5)
            vector_work = retriever.vector_only(query, 5).work_units
            assert result.expansion_admissions <= 3
            assert result.work_units == (
                vector_work + result.expansion_admissions + result.expansion_inspected
            )

    def test_extraction_error_tracks_injected_rates(self) -> None:
        """Measured construction error equals the injected rates (closed loop)."""
        history = seeded_history(11)
        clean = extract_graph(history, ExtractionErrorRates(), seed=5)
        assert graph_construction_error(history, clean)["edge_miss_rate"] == 0.0
        blinded = extract_graph(history, ExtractionErrorRates(edge_miss=1.0), seed=5)
        assert graph_construction_error(history, blinded)["edge_miss_rate"] == 1.0

    def test_spurious_mention_rate_is_guaranteed(self) -> None:
        """mention_spur = 1.0 injects one outside mention per record, always.

        The stray pick comes from entities the record does NOT already
        mention, so the fire can no longer land on a true mention and inject
        nothing — otherwise the realized rate would vary with mention
        breadth and the sensitivity sweep would not be sweeping the named
        rate. (A record mentioning every entity in the vocabulary has no
        outside entity; the corpus here has none of those.)
        """
        history = seeded_history(11)
        spurious = extract_graph(history, ExtractionErrorRates(mention_spur=1.0), seed=5)
        injected = 0
        for record in history.records:
            stray = {
                entity
                for entity in spurious.memberships
                if record.memory_id in spurious.memberships[entity]
                and entity not in record.entities
            }
            assert len(stray) == 1, f"{record.memory_id}: expected exactly 1 stray mention"
            injected += 1
        assert injected == len(history.records)

    def test_extraction_blindness_removes_the_hybrid_gain(self) -> None:
        """100% edge miss on the seeded corpus: hybrid ≡ vector-only.

        The structural floor again, at scale: with no edges there is no
        expansion, so the strategy difference is exactly the graph's
        contribution — nothing else can hide in the fusion code.
        """
        history = seeded_history(11)
        blind_graph = extract_graph(history, ExtractionErrorRates(edge_miss=1.0), seed=5)
        blind = WorkspaceRetriever(history, HashEmbedder(dim=256), blind_graph)
        clean_retriever = self._built(11)[2]
        for query in history.queries[:6]:
            assert blind.hybrid(query, 5).ids == clean_retriever.vector_only(query, 5).ids

    def test_stale_edges_degrade_hybrid_relational_recall(self) -> None:
        """Incorrect-edge sweep: the relational gain dies as spurs rise.

        At spur 0 the gain is maximal (recall 1.0 at k=8). At spur 1.0 every
        true edge is rerouted off its original destination (the error model
        never reroutes onto the destination it replaced) — but a reroute can
        still land ON an anchor from a further hop, so the collapse is not
        the exact no-edges floor (that floor is pinned by the 100% miss
        test): what must hold is that the gain is gone — recall strictly
        below clean and unable to exceed the vector baseline by more than
        the accidental-rescue residue one reroute can buy. The middle rate
        is not asserted monotone: each rate re-rolls the reroutes
        independently, so no rate's edge set contains another's.
        """
        history = seeded_history(11)
        relational = tuple(q for q in history.queries if q.family == "relational")
        recalls: list[float] = []
        for spur in (0.0, 0.5, 1.0):
            graph = extract_graph(history, ExtractionErrorRates(edge_spur=spur), seed=9)
            retriever = WorkspaceRetriever(history, HashEmbedder(dim=256), graph)
            summary = evaluate_strategy(retriever, "hybrid", 8, relational)
            recalls.append(summary["recall"])
        baseline = evaluate_strategy(
            WorkspaceRetriever(history, HashEmbedder(dim=256)), "vector_only", 8, relational
        )
        assert recalls[0] == pytest.approx(1.0)
        assert recalls[1] < recalls[0]
        # Fully stale edges lose the graph gain: at most the baseline plus
        # one accidental rescue (one query's second-order statement reached
        # by a rerouted edge landing back on its anchor).
        assert recalls[2] < recalls[0]
        assert recalls[2] <= baseline["recall"] + 0.25

    def test_stale_fact_leads_repaired_by_demotion_on_seeded_corpus(self) -> None:
        """Temporal family: recency-blind vector leads with stale facts;
        supersession demotion repairs the family mean (budget 0 isolates it)."""
        history, graph, _retriever = self._built(11)
        temporal = tuple(q for q in history.queries if q.family == "temporal")
        assert len(temporal) == 5
        plain = WorkspaceRetriever(history, HashEmbedder(dim=256), graph)
        blind_summary = evaluate_strategy(plain, "vector_only", 2, temporal)
        assert blind_summary["stale_hit_rate"] == pytest.approx(1.0)
        demoting = WorkspaceRetriever(
            history,
            HashEmbedder(dim=256),
            graph,
            StrategyConfig(supersession_gamma=0.25, expansion_budget=0),
        )
        repaired = evaluate_strategy(demoting, "hybrid", 2, temporal)
        assert repaired["stale_hit_rate"] == pytest.approx(0.0)

    def test_provenance_integrity_holds_but_windows_can_orphan(self) -> None:
        """Chain integrity is perfect; tight windows can orphan justifications.

        Two distinct provenance properties, measured separately:

        - chain integrity (completeness) stays 1.0 at scale — every expanded
          hit cites a real source and entity, so no truncation/dedup bug;
        - self-containment: fusion promotes admitted records above their
          admitting witness, so a tight window (k=1 below) returns evidence
          whose source fell outside the cut — the context is not
          self-justifying without a second retrieval. At k=5 on the seeded
          corpus the witness survives; the hand fixture shows the orphan.
        """
        _history, _graph, retriever = self._built(11)
        summary = evaluate_strategy(retriever, "hybrid", 5)
        assert summary["provenance_completeness"] == pytest.approx(1.0)
        assert summary["provenance_self_containment"] == pytest.approx(1.0)
        assert summary["expanded_hits"] > 0.0

    def test_tight_window_orphans_the_expansion_witness(self) -> None:
        """k=1 returns m3 whose chain cites m1 — outside the window.

        m3's fused score (1.25) outranks its admitting candidate m1 (1.0),
        so a one-slot window carries the evidence without its witness. A
        real implementation must either reserve a slot for the witness or
        re-attribute the chain; the metric is what catches the omission.
        """
        retriever = TestHandCheckedArithmetic._retriever()
        query = retriever.history.queries[1]
        result = retriever.hybrid(query, 1)
        assert result.ids == ("m3",)
        assert result.hits[0].provenance[0].from_memory == "m1"
        metrics = score_result(result, query, 1)
        assert metrics["provenance_completeness"] == 1.0
        assert metrics["provenance_self_containment"] == 0.0

    def test_benchmark_report_round_trips(self) -> None:
        """The full per-strategy report is finite, JSON-shaped, and stable."""
        history, graph, retriever = self._built(11)
        report = {
            "vector_only": evaluate_strategy(retriever, "vector_only", 5),
            "vector_recency": evaluate_strategy(retriever, "vector_recency", 5),
            "hybrid": evaluate_strategy(retriever, "hybrid", 5),
            "storage": storage_cost(history, graph, dim=256),
            "construction_error": graph_construction_error(history, graph),
        }
        for name, summary in report.items():
            if name in ("storage", "construction_error"):
                continue
            for key, value in summary.items():
                assert math.isfinite(value), f"{name}.{key} not finite"
        assert report["storage"]["vector_bytes"] == len(history.records) * 256 * 8
        assert report["construction_error"]["edge_miss_rate"] == 0.0
        assert report["vector_only"] == evaluate_strategy(retriever, "vector_only", 5)

    def test_percentile_is_nearest_rank_deterministic(self) -> None:
        """p95 of 15 queries is the 15th ordered value — no interpolation."""
        history, _graph, retriever = self._built(11)
        works = [retriever.run("vector_only", q, 5).work_units for q in history.queries]
        summary = evaluate_strategy(retriever, "vector_only", 5)
        rank = max(1, math.ceil(0.95 * len(works)))
        assert summary["p95_work_units"] == float(sorted(works)[rank - 1])
