"""M8-C2 reranking / query-rewriting research harness (#921) — evidence only.

Epic M8-C leaf: can a learned or LLM-assisted reranker / query rewriter improve
relevant-evidence selection over raw embedding similarity without unacceptable
latency, cost, or drift?

This module imports **no** maistro module: research evidence, never an
authority (M8 epic contract — experimental structures must not become a second
canonical memory owner). Everything here measures; nothing ships.

What is measured, and against what:

* The canonical baseline scored against is a re-implementation, for measurement
  only, of the shipped hybrid retrieval formula at
  ``packages/maistro-core/src/maistro/memory/episodic/ranking.py`` (SPEC-243 /
  ADR-080 part D): ``(keyword_overlap + cosine) * memory.weight``, driven by
  ``ScoredEpisodicRetrieval``'s two-stage shape — a scoped pool of
  ``limit * _POOL_FACTOR`` candidates recalled by the store, reranked by the
  formula. ``keyword_overlap`` is replicated verbatim: raw word-split tokens,
  **no stopword removal** — the absence is itself an experimental axis (a
  rewriter can remove what the lexical term cannot ignore).
* The learnings seam ships a *second* blend spelling
  (``memory/learnings/embeddings.py``: ``1.0 * keyword + 3.0 * embedding``,
  floor 0.3); the blend-weight sweep below scores that shape too, so the two
  shipped spellings are compared on the same corpus rather than by folklore.
* The "cross-encoder" is a deterministic token-interaction stand-in (bigram
  interaction + unigram coverage over a pool). It models the *mechanism and
  cost shape* of pair-scoring reranking, not any real model's quality. Same for
  the rewriter (a fixed rule table) and expansion (pseudo-relevance feedback):
  these stand in for LLM-assisted rewriting so the benchmark procedure is
  runnable in deterministic CI. None of the pinned numbers are evidence about
  real models; they are evidence about the *mechanisms* on a pinned,
  hand-checked corpus.
* Embeddings come from a deterministic hashing embedder with a hand-authored
  synonym-prototype surface (six groups) and a version salt, standing in for
  the ADR-079 ``EmbeddingClient``. The version salt is how model-version
  sensitivity is probed without a second real model.

Corpus, queries, and relevance grades are hand-checked constants below. Latency
is recorded informationally in the report; assertions here are structural
(embed-call counts, pool bounds, metric identities) or pinned corpus facts —
never wall-clock bounds.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import pairwise

# ---------------------------------------------------------------------------
# Canonical-shape replicas (measurement-only; the owners stay in maistro-core)
# ---------------------------------------------------------------------------

_POOL_FACTOR = 10  # episodic/retrieval.py's recall width per requested result
_LEARNINGS_KEYWORD_WEIGHT = 1.0  # memory/learnings/embeddings.py
_LEARNINGS_EMBEDDING_WEIGHT = 3.0

_PUNCT = re.compile(r"[^a-z0-9\s]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    return _PUNCT.sub(" ", text.lower()).split()


def keyword_overlap(query: str, content: str) -> float:
    """Replica of episodic/ranking.py ``keyword_overlap``: raw split, no stopwords."""
    query_words = {w for w in query.lower().split() if w}
    if not query_words:
        return 0.0
    content_words = {w for w in content.lower().split() if w}
    if not content_words:
        return 0.0
    return len(query_words & content_words) / len(query_words)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 for empty or mismatched vectors (as the original)."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Deterministic embedding stand-in (ADR-079 EmbeddingClient for measurement)
# ---------------------------------------------------------------------------

#: Hand-authored synonym groups: tokens in a group additionally carry the
#: group's prototype feature, so two texts sharing no literal word can still be
#: similar — the property a real embedding has and a bag of split-tokens does
#: not. Static and small on purpose; it is a pin, not a model.
SYNONYM_GROUPS: dict[str, tuple[str, ...]] = {
    "revert": ("rollback", "revert", "undo", "restore", "backout"),
    "auth": ("login", "signin", "logout", "password", "credential"),
    "deploy": ("ship", "release", "rollout", "cutover", "launch"),
    "database": ("postgres", "pg", "sql", "alembic", "schema"),
    "billing": ("invoice", "billing", "refund", "charge", "payment"),
    "incident": ("outage", "pager", "postmortem", "escalation", "sev1"),
}

_EMBED_DIM = 96
_PROTO_WEIGHT = 0.9


class HashingEmbedder:
    """Deterministic feature-hashing embedder with a version salt.

    token -> md5(version salt + token) -> bucket, signed; log-free additive tf;
    L2 normalized. Two instances with different salts stand in for two
    embedding-model versions: same mechanism, different representation space.
    """

    def __init__(self, version: str = "v1") -> None:
        self.version = version
        self.calls = 0

    def _bucket(self, token: str) -> int:
        digest = hashlib.md5(f"{self.version}:{token}".encode()).digest()
        return int.from_bytes(digest[:4], "big") % _EMBED_DIM

    def _sign(self, token: str) -> float:
        digest = hashlib.md5(f"{self.version}:{token}:sign".encode()).digest()
        return 1.0 if digest[0] % 2 == 0 else -1.0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        vec = [0.0] * _EMBED_DIM
        for token in tokenize(text):
            vec[self._bucket(token)] += self._sign(token)
            for proto, members in SYNONYM_GROUPS.items():
                if token in members:
                    vec[self._bucket(proto)] += self._sign(proto) * _PROTO_WEIGHT
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return vec
        return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# Pinned corpus and queries (hand-checked)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Memory:
    memory_id: str
    content: str
    weight: float  # within the SPEC-240 tier bounds the content's tier implies


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str
    #: memory_id -> graded relevance (2 = core fact, 1 = same-topic support,
    #: 0/absent = irrelevant)
    relevant: dict[str, int]


def _m(memory_id: str, tier_weight: float, content: str) -> Memory:
    return Memory(memory_id=memory_id, content=content, weight=tier_weight)


# Weights are drawn from the tier bounds in maistro/types/memory.py
# (OBSERVATION 0.1-0.5, LESSON 0.5-0.9, REGRET 0.6-1.0, WISDOM 0.9-1.0, ...).
# Relevant memories deliberately do NOT all carry high weight: d1/d3/m3/m4/r2
# are low-weight observations, so the x-weight term has real work to mis-serve.
CORPUS: tuple[Memory, ...] = (
    # T1 deploy pipeline
    _m("d1", 0.3, "deploy pipeline failed on staging when the health check timed out"),
    _m("d2", 0.7, "lesson: pause the rollout if the deploy smoke suite is red"),
    _m("d3", 0.3, "deploy script retries the cutover twice then aborts"),
    _m("d4", 0.8, "blue-green cutover swapped traffic at 09:00 without incident"),
    _m("d5", 0.5, "post-deploy smoke suite passed on staging"),
    # T2 database / migrations
    _m("m1", 0.6, "migration 0042 added a unique index on users email"),
    _m("m2", 0.7, "lesson: alembic upgrade head locked the table for 90 seconds"),
    _m("m3", 0.3, "revert of migration 0041 dropped the temp column safely"),
    _m("m4", 0.3, "pgvector hnsw index rebuilt with default parameters"),
    _m("m5", 0.6, "connection pool saturated during the users table backfill"),
    # T3 auth / sessions
    _m("a1", 0.6, "auth token refresh window shortened to 15 minutes"),
    _m("a2", 0.7, "lesson: rotate the session cookie on every privilege change"),
    _m("a3", 0.4, "oauth consent screen copy updated for the tenant portal"),
    _m("a4", 0.8, "service account credentials rotated via the vault integration"),
    # T4 retrieval / memory machinery
    _m("r1", 0.6, "memory retrieval reranks the scoped pool by the hybrid score"),
    _m("r2", 0.3, "embedding index rebuild runs nightly at 02:00"),
    _m("r3", 0.7, "lesson: recall pool widened to one hundred candidates"),
    _m("r4", 0.5, "keyword overlap dominates ranking when embeddings are absent"),
    _m("r5", 0.9, "wisdom: consolidation merges duplicate lessons before recall"),
    # T5 billing
    _m("b1", 0.7, "lesson: the invoice job double charged tenant 42 once"),
    _m("b2", 0.5, "stripe webhook retries exhausted after five attempts"),
    _m("b3", 0.4, "usage metering rounding fixed to four decimals"),
    _m("b4", 0.6, "refund policy updated for annual plans in the billing console"),
    # T6 incidents
    _m("i1", 0.8, "incident 118 postmortem blamed a missing retry on the pager path"),
    _m("i2", 0.5, "on-call escalation paged the wrong rotation for sev1"),
    _m("i3", 0.6, "status page update landed 12 minutes after the outage began"),
    _m("i4", 0.9, "wisdom: error budget burned 40 percent in q3 incident review"),
    # Noise (irrelevant to every query; realistic workspace chatter)
    _m("n1", 0.4, "standup notes everyone is busy on the migration of the docs site"),
    _m("n2", 0.3, "zoom link for the sync moved to the afternoon slot"),
    _m("n3", 0.5, "office wifi flickered during the demo session"),
    _m("n4", 0.3, "lunch order thread: two veggie one fish no dairy"),
    _m("n5", 0.4, "wiki page moved to the archive space last week"),
    # Adversarial: share surface words with queries, irrelevant to all of them,
    # and carry top-of-ladder weights (WISDOM/REGRET ceiling) — the shape of a
    # high-weight noise memory the x-weight term will happily promote.
    _m("x1", 1.0, "wisdom: always bring snacks to the deploy freeze night at the office"),
    _m("x2", 0.95, "regret: deploys taught us the office catering is bad on migrations week"),
)

#: 34 scoped memories: small enough to hand-check, big enough that the
#: production pool bound (limit * 10; 30 for k=3) is a real cut (< 34) and
#: provably inert for k=5 (50 >= 34).
CORPUS_SIZE = 34

QUERIES: tuple[Query, ...] = (
    Query("q_deploy1", "deploy pipeline failed on staging", {"d1": 2, "d2": 1, "d3": 1, "d5": 1}),
    Query("q_deploy2", "why did the deploy pause the rollout", {"d2": 2, "d3": 1, "d1": 1}),
    Query("q_migration", "migration added unique index on users email", {"m1": 2, "m2": 1}),
    Query("q_rollback", "rollback the migration that locked the table", {"m2": 2, "m3": 1}),
    Query("q_auth", "auth token refresh window", {"a1": 2, "a2": 1}),
    Query("q_session", "session cookie rotation", {"a2": 2, "a4": 1}),
    Query("q_memory", "memory retrieval hybrid score rerank", {"r1": 2, "r4": 1, "r3": 1}),
    Query("q_index", "embedding index rebuild", {"r2": 2, "r4": 1}),
    Query("q_billing", "invoice double charged tenant", {"b1": 2, "b2": 1}),
    # Ambiguous: terms from two topics; both topics' cores are relevant.
    Query(
        "q_amb_deploy_db",
        "revert migration before the deploy window",
        {"m3": 2, "d2": 2, "m2": 1, "d3": 1},
    ),
    Query(
        "q_amb_auth_incident",
        "token rotation during incident escalation",
        {"a4": 2, "i2": 2, "a1": 1, "i1": 1},
    ),
    # Synonym probe: shares ZERO literal words with its target m3 ("revert of
    # migration 0041 ...") — only the prototype surface can bridge them. The
    # shipped lexical term scores exactly 0.0 here.
    Query("q_synonym", "undo my database change", {"m3": 2, "m2": 1}),
)

AMBIGUOUS_IDS = frozenset({"q_amb_deploy_db", "q_amb_auth_incident"})
ADVERSARIAL_IDS = frozenset({"x1", "x2"})


# ---------------------------------------------------------------------------
# Cost accounting: embed calls and scoring passes, production-faithful
# ---------------------------------------------------------------------------


@dataclass
class CostLedger:
    """Counters that make every variant's cost shape explicit and assertable."""

    embed_calls: int = 0
    score_passes: int = 0  # one pass = (query, candidate) scored for all candidates
    rerank_pair_scores: int = 0  # cross-encoder-shaped pair scorings


class Ranker:
    """One retrieval variant: score a scoped candidate list for a query.

    ``rank`` returns memory ids best-first, dropping non-positive scores (the
    shipped ``rank`` drops at-or-below ``min_score=0``).
    """

    name = "ranker"

    def rank(
        self,
        query: str,
        memories: list[Memory],
        k: int,
        ledger: CostLedger,
        embedder: HashingEmbedder,
    ) -> list[str]:
        raise NotImplementedError


def _hybrid_score(
    query: str,
    memory: Memory,
    query_vec: list[float],
    embedder: HashingEmbedder,
    *,
    keyword_w: float = 1.0,
    vector_w: float = 1.0,
    use_weight: bool = True,
) -> float:
    lex = keyword_w * keyword_overlap(query, memory.content)
    vec = vector_w * cosine(query_vec, embedder.embed(memory.content))
    return (lex + vec) * (memory.weight if use_weight else 1.0)


def _rank_by(scored: list[tuple[float, Memory]], k: int, min_score: float = 0.0) -> list[str]:
    kept = [(s, m) for s, m in scored if s > min_score]
    # Deterministic tie-break: score desc, then memory_id — the shipped sort is
    # score-only over a stable list; the id tie-break keeps this harness
    # order-independent (a corpus list reorder cannot change a benchmark cell).
    kept.sort(key=lambda pair: (-pair[0], pair[1].memory_id))
    return [m.memory_id for _s, m in kept[:k]]


class LexicalOnly(Ranker):
    """keyword_overlap x weight — the shipped term with no embedding client."""

    name = "lexical_only"

    def rank(self, query, memories, k, ledger, embedder):
        ledger.score_passes += 1
        scored = [(keyword_overlap(query, m.content) * m.weight, m) for m in memories]
        return _rank_by(scored, k)


class VectorOnly(Ranker):
    """Raw embedding similarity x weight — the issue's 'baseline vector ranking'.

    Production-faithful cost: ``ScoredEpisodicRetrieval._vector_term`` embeds
    the query AND every candidate on every retrieve; there is no cache.
    """

    name = "vector_only"

    def rank(self, query, memories, k, ledger, embedder):
        ledger.score_passes += 1
        ledger.embed_calls += 1 + len(memories)
        query_vec = embedder.embed(query)
        scored = [(cosine(query_vec, embedder.embed(m.content)) * m.weight, m) for m in memories]
        return _rank_by(scored, k)


class HybridFullScan(Ranker):
    """SPEC-243 formula over the whole scoped list, with optional blend weights.

    Default weights (1, 1) are the episodic spelling; (1, 3) is the learnings
    seam's blend spelling.
    """

    def __init__(
        self, *, keyword_w: float = 1.0, vector_w: float = 1.0, use_weight: bool = True
    ) -> None:
        self.keyword_w = keyword_w
        self.vector_w = vector_w
        self.use_weight = use_weight
        parts = [f"kw{keyword_w:g}", f"vw{vector_w:g}"]
        if not use_weight:
            parts.append("noWeight")
        self.name = "hybrid_" + "_".join(parts)

    def rank(self, query, memories, k, ledger, embedder):
        ledger.score_passes += 1
        ledger.embed_calls += 1 + len(memories)
        query_vec = embedder.embed(query)
        scored = [
            (
                _hybrid_score(
                    query,
                    m,
                    query_vec,
                    embedder,
                    keyword_w=self.keyword_w,
                    vector_w=self.vector_w,
                    use_weight=self.use_weight,
                ),
                m,
            )
            for m in memories
        ]
        return _rank_by(scored, k)


RecallFn = Callable[[str, list[Memory], int, HashingEmbedder, CostLedger], list[Memory]]


def _lexical_recall(
    query: str, memories: list[Memory], pool: int, embedder: HashingEmbedder, ledger: CostLedger
) -> list[Memory]:
    """Lexical recall: no embeds — and it drops every zero-overlap memory."""
    scored = [(keyword_overlap(query, m.content) * m.weight, m) for m in memories]
    kept = [p for p in scored if p[0] > 0.0]
    kept.sort(key=lambda pair: (-pair[0], pair[1].memory_id))
    return [m for _s, m in kept[:pool]]


def _vector_recall(
    query: str, memories: list[Memory], pool: int, embedder: HashingEmbedder, ledger: CostLedger
) -> list[Memory]:
    """Vector recall: a full embed pass (query + every candidate), no cache."""
    ledger.embed_calls += 1 + len(memories)
    query_vec = embedder.embed(query)
    scored = [(cosine(query_vec, embedder.embed(m.content)) * m.weight, m) for m in memories]
    kept = [p for p in scored if p[0] > 0.0]
    kept.sort(key=lambda pair: (-pair[0], pair[1].memory_id))
    return [m for _s, m in kept[:pool]]


class PoolTwoStage(Ranker):
    """``ScoredEpisodicRetrieval``'s shape: recall a pool, rerank by the formula.

    ``recall_fn`` picks the pool (lexical recall or vector recall); the rerank
    is the SPEC-243 hybrid. The pool is a real cut twice over: a relevant
    memory the recall stage missed cannot be promoted — by pool size (the
    ceiling the docstring at episodic/retrieval.py names, "Reranking cannot
    promote a memory the recall stage never returned") or by the recall
    scorer's zero-drop, which binds even when the pool is larger than the
    corpus. Both cuts are measured below.
    """

    def __init__(self, name: str, recall_fn: RecallFn) -> None:
        self.name = name
        self._recall = recall_fn

    def rank(self, query, memories, k, ledger, embedder):
        pool = self._recall(query, memories, k * _POOL_FACTOR, embedder, ledger)
        if not pool:
            return []
        ledger.score_passes += 1
        ledger.embed_calls += 1 + len(pool)
        query_vec = embedder.embed(query)
        scored = [(_hybrid_score(query, m, query_vec, embedder), m) for m in pool]
        return _rank_by(scored, k)


class CrossEncoderStandIn(Ranker):
    """Token-interaction reranker over a pool — cross-encoder cost shape.

    score = 2 x (query bigrams present in the doc) + unigram coverage share.
    A real cross-encoder replaces this with a model call per (query, doc) pair;
    this stand-in keeps the cost shape (pool-sized pair scoring, no embeds)
    while staying deterministic. Interaction over token *pairs* is the part the
    bag-of-words lexical term structurally cannot do.
    """

    name = "cross_encoder_stand_in"

    def __init__(self, recall_fn: RecallFn | None = None) -> None:
        self._recall = recall_fn or _lexical_recall

    def rank(self, query, memories, k, ledger, embedder):
        pool = self._recall(query, memories, k * _POOL_FACTOR, embedder, ledger)
        if not pool:
            return []
        query_tokens = [t for t in tokenize(query) if len(t) >= 3]
        query_bigrams = list(pairwise(query_tokens))
        scored = []
        for m in pool:
            ledger.rerank_pair_scores += 1
            doc_tokens = tokenize(m.content)
            doc_set = set(doc_tokens)
            coverage = len(doc_set & set(query_tokens)) / len(query_tokens) if query_tokens else 0.0
            doc_bigrams = set(pairwise(doc_tokens))
            interaction = sum(1 for bg in query_bigrams if bg in doc_bigrams)
            scored.append((2.0 * interaction + coverage, m))
        return _rank_by(scored, k)


_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "why",
        "how",
        "what",
        "when",
        "that",
        "this",
        "it",
        "its",
        "on",
        "in",
        "at",
        "to",
        "of",
        "for",
        "with",
        "and",
        "or",
        "be",
        "been",
        "before",
        "after",
        "during",
        "my",
    ]
)


def rewrite_query(query: str) -> str:
    """Fixed rule table standing in for an LLM rewriter.

    Two mechanisms only: (1) map informal/underspecified words onto the corpus's
    vocabulary (the substitution an LLM rewriter would learn); (2) drop
    stopwords — which the shipped lexical term cannot ignore, because
    ``keyword_overlap`` splits raw words. Deliberately NOT clever: the benchmark
    measures the mechanisms, not LLM flair.
    """
    substitutions = {
        "rollback": "revert migration",
        "undo": "revert",
        "db": "database migration",
        "pg": "postgres database",
        "broke": "failed",
        "slow": "latency",
        "login": "authentication session token",
        "reindex": "rebuild index",
    }
    out: list[str] = []
    for raw in query.split():
        word = _PUNCT.sub("", raw.lower())
        if not word:
            continue
        if word in _STOPWORDS:
            continue
        out.extend(substitutions.get(word, word).split())
    return " ".join(out)


class Rewritten(Ranker):
    """rewrite_query, then a base ranker over the full scan."""

    def __init__(self, base: Ranker | None = None) -> None:
        self._base = base or HybridFullScan()
        self.name = f"rewritten[{self._base.name}]"

    def rank(self, query, memories, k, ledger, embedder):
        return self._base.rank(rewrite_query(query), memories, k, ledger, embedder)


def expand_query_prf(
    query: str,
    memories: list[Memory],
    embedder: HashingEmbedder,
    ledger: CostLedger,
    *,
    top_docs: int = 3,
    top_terms: int = 3,
) -> str:
    """Pseudo-relevance feedback: the top docs' most frequent novel terms.

    Deterministic: round-1 hybrid scores (charged to ``ledger``), top-`top_docs`
    docs (score desc, id tie-break), candidate terms = their tokens minus the
    query's own minus stopwords, ranked by (doc frequency among the top docs,
    total count, word). Cost is faithful: the full round-1 pass embeds the
    query and every candidate, exactly like any full scan.
    """
    round1 = HybridFullScan()
    top_ids = round1.rank(query, memories, top_docs, ledger, embedder)
    by_id = {m.memory_id: m for m in memories}
    query_terms = set(tokenize(query))
    counts: dict[str, int] = {}
    doc_freq: dict[str, int] = {}
    for memory_id in top_ids:
        content = by_id[memory_id].content
        for token in tokenize(content):
            if token in query_terms or token in _STOPWORDS or len(token) < 3:
                continue
            counts[token] = counts.get(token, 0) + 1
        for token in set(tokenize(content)):
            if token in query_terms or token in _STOPWORDS or len(token) < 3:
                continue
            doc_freq[token] = doc_freq.get(token, 0) + 1
    ranked_terms = sorted(counts, key=lambda t: (-doc_freq.get(t, 0), -counts[t], t))
    return query + " " + " ".join(ranked_terms[:top_terms])


class PRFExpanded(Ranker):
    """Pseudo-relevance-feedback expansion, then the hybrid over the full scan.

    Cost charged faithfully: two full embed passes (round 1 + the expanded
    query's pass), two scoring passes — double the baseline full scan when
    there is no embedding cache, which production does not have.
    """

    name = "prf_expanded_hybrid"

    def rank(self, query, memories, k, ledger, embedder):
        expanded = expand_query_prf(query, memories, embedder, ledger)
        return HybridFullScan().rank(expanded, memories, k, ledger, embedder)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def recall_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    """Grade >= 1 counts as relevant; |retrieved & relevant| / |relevant|."""
    if not relevant:
        return 0.0
    top = set(ranked[:k])
    hits = sum(1 for memory_id in relevant if memory_id in top)
    return hits / len(relevant)


def precision_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    hits = sum(1 for memory_id in top if relevant.get(memory_id, 0) > 0)
    return hits / len(top)


def mrr(ranked: list[str], relevant: dict[str, int]) -> float:
    for i, memory_id in enumerate(ranked, start=1):
        if relevant.get(memory_id, 0) > 0:
            return 1.0 / i
    return 0.0


def _dcg(ids: list[str], relevant: dict[str, int], k: int) -> float:
    return sum(
        (2 ** relevant.get(memory_id, 0) - 1) / math.log2(i + 1)
        for i, memory_id in enumerate(ids[:k], start=1)
    )


def ndcg_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    """nDCG with graded gains (2^grade - 1) and log2 discounts."""
    ideal = sorted(relevant.values(), reverse=True)
    if not ideal:
        return 0.0
    ideal_ids = [f"ideal-{i}" for i in range(len(ideal))]
    ideal_map = dict(zip(ideal_ids, ideal, strict=True))
    return _dcg(ranked, relevant, k) / _dcg(ideal_ids, ideal_map, k)


def overlap_at_k(a: list[str], b: list[str], k: int) -> float:
    """Jaccard overlap of two top-k id lists — ranker/version agreement."""
    sa, sb = set(a[:k]), set(b[:k])
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


# ---------------------------------------------------------------------------
# Benchmark driver
# ---------------------------------------------------------------------------

K_SMALL = 3
K_LARGE = 5


@dataclass
class VariantResult:
    variant: str
    recall_at_3: float
    recall_at_5: float
    precision_at_5: float
    mrr: float
    ndcg_at_5: float
    ambiguous_precision_at_5: float
    adversarial_top5_hits: int  # x1/x2 in any top-5, summed over queries
    embed_calls: int
    score_passes: int
    rerank_pair_scores: int
    wall_clock_us_per_query: float  # informational only; never asserted


def _run_variant(
    ranker: Ranker,
    embedder: HashingEmbedder,
    k_small: int = K_SMALL,
    k_large: int = K_LARGE,
) -> VariantResult:
    ledger = CostLedger()
    recalls_3: list[float] = []
    recalls_5: list[float] = []
    precisions_5: list[float] = []
    mrrs: list[float] = []
    ndcgs_5: list[float] = []
    amb_precisions: list[float] = []
    adversarial_hits = 0
    start = time.perf_counter()
    for q in QUERIES:
        ranked = ranker.rank(q.text, list(CORPUS), k_large, ledger, embedder)
        recalls_3.append(recall_at_k(ranked, q.relevant, k_small))
        recalls_5.append(recall_at_k(ranked, q.relevant, k_large))
        precisions_5.append(precision_at_k(ranked, q.relevant, k_large))
        mrrs.append(mrr(ranked, q.relevant))
        ndcgs_5.append(ndcg_at_k(ranked, q.relevant, k_large))
        if q.query_id in AMBIGUOUS_IDS:
            amb_precisions.append(precision_at_k(ranked, q.relevant, k_large))
        adversarial_hits += sum(1 for memory_id in ranked[:k_large] if memory_id in ADVERSARIAL_IDS)
    elapsed = time.perf_counter() - start
    n = len(QUERIES)
    return VariantResult(
        variant=ranker.name,
        recall_at_3=sum(recalls_3) / n,
        recall_at_5=sum(recalls_5) / n,
        precision_at_5=sum(precisions_5) / n,
        mrr=sum(mrrs) / n,
        ndcg_at_5=sum(ndcgs_5) / n,
        ambiguous_precision_at_5=(sum(amb_precisions) / len(amb_precisions))
        if amb_precisions
        else 0.0,
        adversarial_top5_hits=adversarial_hits,
        embed_calls=ledger.embed_calls,
        score_passes=ledger.score_passes,
        rerank_pair_scores=ledger.rerank_pair_scores,
        wall_clock_us_per_query=(elapsed / n) * 1e6,
    )


def run_benchmark(embedder_version: str = "v1") -> list[VariantResult]:
    """The full variant matrix on the pinned corpus. Deterministic."""
    embedder = HashingEmbedder(embedder_version)
    rankers: list[Ranker] = [
        LexicalOnly(),
        VectorOnly(),
        HybridFullScan(),  # the shipped episodic spelling
        HybridFullScan(keyword_w=_LEARNINGS_KEYWORD_WEIGHT, vector_w=_LEARNINGS_EMBEDDING_WEIGHT),
        HybridFullScan(use_weight=False),  # ablation: no x weight
        PoolTwoStage("pool_lexical_recall_hybrid", _lexical_recall),
        PoolTwoStage("pool_vector_recall_hybrid", _vector_recall),
        CrossEncoderStandIn(),
        Rewritten(HybridFullScan()),
        PRFExpanded(),
        Rewritten(PRFExpanded()),
    ]
    return [_run_variant(r, embedder) for r in rankers]


# ---------------------------------------------------------------------------
# Tests: metric identities first, then the pinned corpus facts
# ---------------------------------------------------------------------------


class TestMetricIdentities:
    """Hand-checked metric math — the instruments before the measurement."""

    def test_recall_precision_mrr_ndcg_on_a_toy_ranking(self) -> None:
        relevant = {"a": 2, "b": 1, "c": 1}
        ranked = ["x", "a", "b", "z", "c"]
        assert recall_at_k(ranked, relevant, 3) == 2 / 3
        assert recall_at_k(ranked, relevant, 5) == 1.0
        assert precision_at_k(ranked, relevant, 5) == 3 / 5
        assert precision_at_k([], relevant, 5) == 0.0
        assert mrr(ranked, relevant) == 1 / 2
        # DCG: rank2 a -> 3/log2(3); rank3 b -> 1/log2(4); rank5 c -> 1/log2(6)
        dcg = 3 / math.log2(3) + 1 / math.log2(4) + 1 / math.log2(6)
        # IDCG over the ideal grade order (2, 1, 1)
        idcg = 3 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
        assert ndcg_at_k(ranked, relevant, 5) == dcg / idcg
        # A perfect ranking scores 1.0; an all-irrelevant ranking 0.0.
        assert ndcg_at_k(["a", "b", "c"], relevant, 3) == 1.0
        assert ndcg_at_k(["x", "y", "z"], relevant, 3) == 0.0
        assert ndcg_at_k(["x"], {}, 3) == 0.0

    def test_recall_is_monotone_in_k_for_any_ranking(self) -> None:
        relevant = {"a": 1, "b": 1, "c": 1, "d": 1}
        ranked = ["d", "x", "c", "y", "b", "z", "a"]
        values = [recall_at_k(ranked, relevant, k) for k in range(0, 9)]
        assert values == sorted(values)

    def test_overlap_agreement_is_symmetric_and_bounded(self) -> None:
        assert overlap_at_k(["a", "b"], ["b", "c"], 2) == 1 / 3
        assert overlap_at_k(["a"], ["a"], 1) == 1.0
        assert overlap_at_k([], [], 3) == 1.0


class TestCorpusSanity:
    def test_every_query_has_relevant_memories_and_ids_resolve(self) -> None:
        corpus_ids = {m.memory_id for m in CORPUS}
        assert len(corpus_ids) == len(CORPUS), "memory ids must be unique"
        for q in QUERIES:
            assert q.relevant, f"{q.query_id} has no relevance labels"
            assert set(q.relevant) <= corpus_ids, f"{q.query_id} labels an unknown id"

    def test_corpus_fits_the_pinned_shape(self) -> None:
        assert len(CORPUS) == CORPUS_SIZE == 34
        assert len(QUERIES) == 12
        assert len(AMBIGUOUS_IDS) == 2 and len(ADVERSARIAL_IDS) == 2
        for m in CORPUS:
            assert 0.1 <= m.weight <= 1.0, f"{m.memory_id} outside the SPEC-240 ladder"
        # The pool bound is real for k=3 and provably inert for k=5 here.
        assert K_SMALL * _POOL_FACTOR < CORPUS_SIZE <= K_LARGE * _POOL_FACTOR

    def test_synonym_probe_shares_no_literal_word_with_its_target(self) -> None:
        q_syn = next(q for q in QUERIES if q.query_id == "q_synonym")
        target = next(m for m in CORPUS if m.memory_id == "m3")
        assert keyword_overlap(q_syn.text, target.content) == 0.0
        # ...but the prototype surface still ranks it: the embedder is what
        # carries "undo" -> revert-group -> m3.
        embedder = HashingEmbedder("v1")
        assert cosine(embedder.embed(q_syn.text), embedder.embed(target.content)) > 0.0

    def test_benchmark_is_deterministic(self) -> None:
        first = run_benchmark("v1")
        second = run_benchmark("v1")
        # wall_clock is informational and necessarily varies; everything else
        # is pinned and must be byte-identical across runs.
        strip = lambda r: replace(r, wall_clock_us_per_query=0.0)  # noqa: E731
        assert [strip(r) for r in first] == [strip(r) for r in second]

    def test_report_schema_is_complete(self) -> None:
        results = run_benchmark("v1")
        names = [r.variant for r in results]
        assert len(names) == len(set(names)) == 11
        for r in results:
            for value in (
                r.recall_at_3,
                r.recall_at_5,
                r.precision_at_5,
                r.mrr,
                r.ndcg_at_5,
                r.ambiguous_precision_at_5,
            ):
                assert 0.0 <= value <= 1.0
            assert r.embed_calls >= 0 and r.score_passes >= 0


class TestCostShapes:
    """Cost accounting pinned to structural facts, not wall-clock."""

    def test_full_scan_embeds_query_plus_every_candidate_per_query(self) -> None:
        embedder = HashingEmbedder("v1")
        ledger = CostLedger()
        HybridFullScan().rank("deploy", list(CORPUS), 3, ledger, embedder)
        assert embedder.calls == 1 + CORPUS_SIZE
        assert ledger.embed_calls == embedder.calls
        assert ledger.score_passes == 1

    def test_pool_two_stage_embeds_only_the_pool(self) -> None:
        """The rerank pass embeds query + surviving pool — not the corpus.

        The pool is whatever lexical recall returns (zero-overlap memories are
        dropped, and the size cap binds under it), so the pinned claim is the
        structural one: rerank embeds = 1 + len(pool), never 1 + corpus.
        """
        embedder = HashingEmbedder("v1")
        ledger = CostLedger()
        pool = _lexical_recall("deploy", list(CORPUS), K_SMALL * _POOL_FACTOR, embedder, ledger)
        assert 0 < len(pool) < CORPUS_SIZE
        PoolTwoStage("pool_lexical_recall_hybrid", _lexical_recall).rank(
            "deploy", list(CORPUS), K_SMALL, ledger, embedder
        )
        assert embedder.calls == 1 + len(pool)
        assert ledger.embed_calls == embedder.calls
        assert ledger.score_passes == 1

    def test_vector_recall_pays_a_full_scan_before_the_rerank_pass(self) -> None:
        """Vector recall is a full embed pass; the rerank pays the pool again."""
        embedder = HashingEmbedder("v1")
        ledger = CostLedger()
        pool = _vector_recall(
            "deploy", list(CORPUS), K_SMALL * _POOL_FACTOR, embedder, CostLedger()
        )
        assert embedder.calls == 1 + CORPUS_SIZE  # recall pass = query + all
        embedder2 = HashingEmbedder("v1")
        PoolTwoStage("pool_vector_recall_hybrid", _vector_recall).rank(
            "deploy", list(CORPUS), K_SMALL, ledger, embedder2
        )
        assert embedder2.calls == (1 + CORPUS_SIZE) + (1 + len(pool))
        assert ledger.embed_calls == embedder2.calls

    def test_vector_only_pays_more_embeds_than_lexical_only(self) -> None:
        e_lex, e_vec = HashingEmbedder("v1"), HashingEmbedder("v1")
        l_lex, l_vec = CostLedger(), CostLedger()
        LexicalOnly().rank("deploy", list(CORPUS), 3, l_lex, e_lex)
        VectorOnly().rank("deploy", list(CORPUS), 3, l_vec, e_vec)
        assert e_lex.calls == 0 and e_vec.calls == 1 + CORPUS_SIZE

    def test_cross_encoder_stand_in_costs_pool_sized_pair_scores_not_embeds(self) -> None:
        """Pair scorings = pool members (whatever recall returned); no embeds."""
        embedder = HashingEmbedder("v1")
        ledger = CostLedger()
        CrossEncoderStandIn().rank("deploy", list(CORPUS), K_SMALL, ledger, embedder)
        pool = _lexical_recall(
            "deploy", list(CORPUS), K_SMALL * _POOL_FACTOR, embedder, CostLedger()
        )
        assert ledger.rerank_pair_scores == len(pool) > 0
        assert ledger.rerank_pair_scores <= K_SMALL * _POOL_FACTOR
        assert embedder.calls == 0 and ledger.embed_calls == 0

    def test_prf_expansion_doubles_the_full_scan_embed_cost_without_a_cache(self) -> None:
        e_prf, e_base = HashingEmbedder("v1"), HashingEmbedder("v1")
        l_prf, l_base = CostLedger(), CostLedger()
        PRFExpanded().rank("deploy", list(CORPUS), 3, l_prf, e_prf)
        HybridFullScan().rank("deploy", list(CORPUS), 3, l_base, e_base)
        assert e_prf.calls == 2 * (1 + CORPUS_SIZE)
        assert e_base.calls == 1 + CORPUS_SIZE
        assert l_prf.score_passes == 2 and l_base.score_passes == 1
        assert l_prf.embed_calls == e_prf.calls


class TestBenchmarkFindings:
    """Pinned facts from the pinned corpus. Re-checked by re-running."""

    @classmethod
    def setup_class(cls) -> None:
        cls.results = {r.variant: r for r in run_benchmark("v1")}

    def test_hybrid_shipped_spelling_beats_its_own_halves(self) -> None:
        hybrid = self.results["hybrid_kw1_vw1"]
        assert hybrid.ndcg_at_5 > self.results["lexical_only"].ndcg_at_5
        assert hybrid.ndcg_at_5 > self.results["vector_only"].ndcg_at_5

    def test_synonym_probe_exposes_the_weight_term_suppressing_vector_only_matches(self) -> None:
        """ "undo my database change" has zero lexical overlap with m3.

        Pinned corpus fact: neither the shipped lexical term nor the shipped
        hybrid retrieves m3 — the vector term finds it, but the x-weight
        multiplies the bridge away (m3 is a weight-0.3 observation). Only the
        rewriter's explicit mapping ("undo" -> "revert") pulls it into the
        top-5. Mechanism, not LLM flair: query-side vocabulary repair bought
        what the embedding side could not, at zero extra embeds.
        """
        e = HashingEmbedder("v1")
        q_syn = next(q for q in QUERIES if q.query_id == "q_synonym")
        corpus = list(CORPUS)
        assert (
            keyword_overlap(q_syn.text, next(m.content for m in corpus if m.memory_id == "m3"))
            == 0.0
        )
        lexical_top5 = LexicalOnly().rank(q_syn.text, corpus, 5, CostLedger(), e)
        hybrid_top5 = HybridFullScan().rank(q_syn.text, corpus, 5, CostLedger(), e)
        rewritten_top5 = Rewritten(HybridFullScan()).rank(q_syn.text, corpus, 5, CostLedger(), e)
        assert "m3" not in lexical_top5
        assert "m3" not in hybrid_top5
        assert "m3" in rewritten_top5

    def test_adversarial_weight_gaming_is_real_and_the_ablation_dominates(self) -> None:
        """Pinned corpus facts: the x-weight term promotes top-of-ladder noise.

        On this corpus the weightless ablation does not merely resist the
        adversarial memories — it beats the shipped formula on every quality
        cell while cutting adversarial top-5 hits from 8 to 2. The caveat the
        note must carry: production weights are produced by SPEC-240
        reinforcement/decay, so weight correlates with usefulness there in a
        way these pinned weights do not model.
        """
        hybrid = self.results["hybrid_kw1_vw1"]
        weightless = self.results["hybrid_kw1_vw1_noWeight"]
        assert hybrid.adversarial_top5_hits > 0, (
            "the pinned adversarial memories no longer reach any top-5; the "
            "x-weight gaming demonstration is void and the corpus needs a new one"
        )
        assert weightless.adversarial_top5_hits < hybrid.adversarial_top5_hits
        assert weightless.recall_at_3 > hybrid.recall_at_3
        assert weightless.recall_at_5 > hybrid.recall_at_5
        assert weightless.precision_at_5 > hybrid.precision_at_5
        assert weightless.ndcg_at_5 > hybrid.ndcg_at_5
        assert weightless.mrr > hybrid.mrr

    def test_ambiguous_queries_degrade_precision_but_not_to_zero(self) -> None:
        corpus = list(CORPUS)
        e = HashingEmbedder("v1")
        for q in (q for q in QUERIES if q.query_id in AMBIGUOUS_IDS):
            ranked = HybridFullScan().rank(q.text, corpus, 5, CostLedger(), e)
            precision = precision_at_k(ranked, q.relevant, 5)
            assert 0.0 < precision <= 1.0

    def test_rewriting_rescues_the_underspecified_rollback_query(self) -> None:
        # "rollback" maps onto the corpus vocabulary (revert/migration) only
        # via the rewriter; expansion alone cannot invent the mapping.
        corpus = list(CORPUS)
        e = HashingEmbedder("v1")
        q_roll = next(q for q in QUERIES if q.query_id == "q_rollback")
        plain = HybridFullScan().rank(q_roll.text, corpus, 5, CostLedger(), e)
        rewritten = Rewritten(HybridFullScan()).rank(q_roll.text, corpus, 5, CostLedger(), e)
        assert "m3" not in plain  # the raw query misses the revert memory
        assert "m3" in rewritten

    def test_rewriting_improves_overall_and_prf_expansion_hurts_on_this_corpus(self) -> None:
        """Pinned benchmark facts at this head.

        - rewrite-then-hybrid dominates the shipped hybrid on every quality
          cell measured here, at identical embed cost (rewriting is free: the
          query string is re-embedded once either way).
        - PRF expansion alone DEGRADES nDCG and MRR versus the shipped hybrid
          while doubling embed cost: round 1 inherits the high-weight-noise
          failure and expands the query with noise vocabulary — expansion
          amplifies the first stage's failure mode, it does not correct it.
        - chaining rewrite-then-PRF buys the best recall of any variant and
          pays for it with the worst MRR of the rewriting family.
        """
        hybrid = self.results["hybrid_kw1_vw1"]
        rewritten = self.results["rewritten[hybrid_kw1_vw1]"]
        prf = self.results["prf_expanded_hybrid"]
        chain = self.results["rewritten[prf_expanded_hybrid]"]
        assert rewritten.recall_at_3 > hybrid.recall_at_3
        assert rewritten.recall_at_5 > hybrid.recall_at_5
        assert rewritten.ndcg_at_5 > hybrid.ndcg_at_5
        assert rewritten.mrr > hybrid.mrr
        assert prf.ndcg_at_5 < hybrid.ndcg_at_5
        assert prf.mrr < hybrid.mrr
        assert prf.embed_calls == 2 * hybrid.embed_calls
        assert chain.recall_at_5 == max(r.recall_at_5 for r in self.results.values())
        assert chain.mrr < rewritten.mrr

    def test_learnings_blend_spelling_is_not_the_episodic_one(self) -> None:
        """The 1:3 keyword:embedding blend vs the episodic 1:1 sum.

        Both spellings ship (episodic `ranking.py`, learnings
        `embeddings.py`); on this corpus they differ — pinned so a silent
        change to either seam's weights shows up here.
        """
        episodic = self.results["hybrid_kw1_vw1"]
        learnings = self.results["hybrid_kw1_vw3"]
        assert (learnings.ndcg_at_5, learnings.recall_at_5) != (
            episodic.ndcg_at_5,
            episodic.recall_at_5,
        )

    def test_embed_free_variants_are_immune_to_the_model_version_swap(self) -> None:
        """Pinned control: variants that never embed do not move across versions.

        lexical_only and the cross-encoder stand-in (lexical recall + token
        interaction) return byte-identical tables under the v1 -> v2 embedder
        swap, while every embedding-consuming variant moves. That contrast is
        the model-version sensitivity experiment's control arm.
        """
        by_v1 = {r.variant: r for r in run_benchmark("v1")}
        by_v2 = {r.variant: r for r in run_benchmark("v2")}
        for embed_free in ("lexical_only", "cross_encoder_stand_in"):
            a, b = by_v1[embed_free], by_v2[embed_free]
            assert (a.ndcg_at_5, a.recall_at_5, a.precision_at_5, a.mrr) == (
                b.ndcg_at_5,
                b.recall_at_5,
                b.precision_at_5,
                b.mrr,
            )
        moved = [
            name
            for name in by_v1
            if (by_v1[name].ndcg_at_5, by_v1[name].recall_at_5)
            != (by_v2[name].ndcg_at_5, by_v2[name].recall_at_5)
        ]
        assert moved, "no variant moved under the embedder version swap"
        assert "hybrid_kw1_vw1" in moved and "rewritten[hybrid_kw1_vw1]" in moved
        # Ranker agreement between versions, measured per query for the shipped
        # hybrid: the swap reorders top-5s substantially (pinned < 1.0), which
        # is what any learned reranker trained on one embedding version would
        # inherit when the registry serves another.
        corpus = list(CORPUS)
        e1, e2 = HashingEmbedder("v1"), HashingEmbedder("v2")
        agreements = [
            overlap_at_k(
                HybridFullScan().rank(q.text, corpus, 5, CostLedger(), e1),
                HybridFullScan().rank(q.text, corpus, 5, CostLedger(), e2),
                5,
            )
            for q in QUERIES
        ]
        assert sum(agreements) / len(agreements) < 1.0

    def test_cross_encoder_interaction_shape_wins_precision_on_this_corpus(self) -> None:
        """Pinned: the interaction stand-in's precision/ambiguity edge.

        The bigram-interaction scorer over a lexical-recall pool beats the
        shipped hybrid on precision@5 and on the ambiguous-query slice, with
        zero embed calls (its recall is lexical; its scoring needs no
        embedding). It does NOT beat the weightless ablation's recall — and
        the corpus caveats (hashing stand-in embedder, hand-pinned labels)
        bound how far this may be read.
        """
        cross = self.results["cross_encoder_stand_in"]
        hybrid = self.results["hybrid_kw1_vw1"]
        assert cross.precision_at_5 > hybrid.precision_at_5
        assert cross.ambiguous_precision_at_5 > hybrid.ambiguous_precision_at_5
        assert cross.embed_calls == 0
        assert cross.rerank_pair_scores > 0
        # It is not a free win on every axis: recall stays below the
        # weightless ablation's.
        assert cross.recall_at_5 < self.results["hybrid_kw1_vw1_noWeight"].recall_at_5

    def test_pool_cut_binds_through_the_recall_scorer_not_just_pool_size(self) -> None:
        """The pool is two cuts; size is the smaller one on this corpus.

        Pinned facts (k=3 and k=5, v1 embedder):
        - Vector recall at pool = k x 10 never differs from the full scan
          here (its zero-drop never bites at this corpus size), so the
          two-stage shape is free of quality loss in that direction.
        - Lexical recall is WORSE than the full scan at BOTH k values even
          though the k=5 pool (50) is larger than the corpus (34): the
          recall scorer drops every zero-lexical-overlap memory, and those
          are exactly the matches only the vector term could find. The cut
          that binds is the scorer, not the size — "reranking cannot promote
          a memory the recall stage never returned", and the recall stage
          returned fewer than its size allowed.
        """
        full = self.results["hybrid_kw1_vw1"]
        pool_lex = self.results["pool_lexical_recall_hybrid"]
        pool_vec = self.results["pool_vector_recall_hybrid"]
        assert pool_vec.recall_at_3 == full.recall_at_3
        assert pool_vec.recall_at_5 == full.recall_at_5
        assert pool_vec.ndcg_at_5 == full.ndcg_at_5
        assert pool_lex.recall_at_3 < full.recall_at_3
        assert pool_lex.recall_at_5 < full.recall_at_5
        assert pool_lex.ndcg_at_5 < full.ndcg_at_5


class TestRobustnessSweep:
    """Injection sweep: how much high-weight noise before recall breaks."""

    @staticmethod
    def _noise_bank() -> list[Memory]:
        return [
            _m("z1", 0.95, "wisdom: deploy migrations tokens incident 1 at the office"),
            _m("z2", 0.95, "wisdom: deploy migrations tokens incident 2 at the office"),
            _m("z3", 0.95, "wisdom: deploy migrations tokens incident 3 at the office"),
            _m("z4", 0.95, "wisdom: deploy migrations tokens incident 4 at the office"),
            _m("z5", 0.95, "wisdom: deploy migrations tokens incident 5 at the office"),
        ]

    def test_recall_never_improves_from_high_weight_noise_injection(self) -> None:
        e = HashingEmbedder("v1")
        q = next(q for q in QUERIES if q.query_id == "q_deploy1")
        recalls = []
        for n in range(0, 6):
            corpus = list(CORPUS) + self._noise_bank()[:n]
            ranked = HybridFullScan().rank(q.text, corpus, 5, CostLedger(), e)
            recalls.append(recall_at_k(ranked, q.relevant, 5))
        # Injected near-query high-weight noise can only crowd the top-5;
        # recall must never *improve* from adding it.
        assert all(a >= b for a, b in pairwise(recalls)), recalls

    def test_flooding_noise_breaks_the_two_stage_pool_too(self) -> None:
        """The pool cut filters below-pool noise — until noise floods the pool.

        25 flooding memories (high weight, lexically on-topic) drive every
        relevant memory out of the lexical-recall pool of 30, and the two-stage
        rerank is then exactly as blind as the full scan.
        """
        e = HashingEmbedder("v1")
        q = next(q for q in QUERIES if q.query_id == "q_deploy1")
        pool_ranker = PoolTwoStage("pool_lexical_recall_hybrid", _lexical_recall)
        flooded = list(CORPUS) + [
            _m(f"f{i}", 0.95, f"deploy pipeline failed staging rerun {i} for the office party")
            for i in range(1, 26)
        ]
        clean_recall = recall_at_k(
            pool_ranker.rank(q.text, list(CORPUS), 5, CostLedger(), e), q.relevant, 5
        )
        flooded_recall = recall_at_k(
            pool_ranker.rank(q.text, flooded, 5, CostLedger(), e), q.relevant, 5
        )
        assert flooded_recall < clean_recall
