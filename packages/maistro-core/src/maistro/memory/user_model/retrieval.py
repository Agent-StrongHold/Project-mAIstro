"""Relevance-gated recall from the user model (#1047, SPEC-243 flavor).

Authorized access does not imply context injection. ``recall`` is the only
read path that feeds a task prompt, and it scores and filters before it
returns: a fact that does not match the current Persona, task or Workspace is
left out even though the caller is authorized to read it. The desired
experience is surprising relevance, not indiscriminate leakage.

Scoring is deterministic: ``RecallQuery.now`` fixes the clock so a test can
assert structure instead of wall-clock timing. The formula follows
SPEC-243's shape -- ``(lexical + persona + workspace affinity) * confidence
* recency`` -- with pgvector-style embedding similarity deliberately absent:
user-model facts are short normalized statements, and no embedding column is
claimed for them (ADR-082326-8194 covers the episodic embedding column only).

Persona affects ranking only. It can lift or sink a fact, never widen who may
read it -- ownership filtering is done by the store before any scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.memory.user_model.types import FactSensitivity, FactState, UserModelFact

if TYPE_CHECKING:
    from maistro.protocols.memory import UserModelStore

#: A 30-day half-life: recency halves every month of silence. Facts do not
#: decay out of the model (ADR-092526-4391), but their recall score does age.
_RECENCY_HALF_LIFE_DAYS = 30.0

#: Terms shorter than this carry no topical signal ("7d" vs "the").
_MIN_TERM_LEN = 3

#: Rank ordering for sensitivity caps: a query surface opts into how sensitive
#: a fact it is willing to see. SENSITIVE facts need an explicit opt-in.
_SENSITIVITY_RANK = {
    FactSensitivity.NORMAL: 0,
    FactSensitivity.PERSONAL: 1,
    FactSensitivity.SENSITIVE: 2,
}

_WORD_RE = re.compile(r"[a-z0-9]+")

#: Closed-class words that never carry relevance signal on their own.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "has",
        "have",
        "was",
        "were",
        "are",
        "but",
        "not",
        "you",
        "your",
        "his",
        "her",
        "their",
        "its",
        "our",
        "who",
        "whom",
        "which",
        "what",
        "when",
        "where",
        "how",
        "why",
        "all",
        "any",
        "can",
        "will",
        "would",
        "should",
        "could",
        "into",
        "onto",
        "about",
        "after",
        "before",
        "over",
        "under",
        "again",
        "then",
        "than",
        "them",
        "they",
        "she",
        "him",
        "had",
        "did",
        "does",
        "done",
        "being",
        "been",
        "because",
        "while",
        "during",
        "without",
        "within",
        "upon",
        "per",
        "via",
        "also",
        "just",
        "very",
        "own",
        "same",
        "too",
        "such",
        "only",
        "more",
        "most",
        "some",
        "both",
        "each",
        "few",
    }
)


def _terms(text: str) -> frozenset[str]:
    """Topical terms of one text, case- and punctuation-insensitive.

    A conservative plural fold ("shoots" -> "shoot") keeps recall from
    missing a fact over inflection alone; it never folds anything shorter
    than five characters, so "lens" stays "lens".
    """
    terms: set[str] = set()
    for term in _WORD_RE.findall(text.casefold()):
        if len(term) < _MIN_TERM_LEN or term in _STOPWORDS:
            continue
        terms.add(term)
        if len(term) >= 5 and term.endswith("s") and not term.endswith("ss"):
            terms.add(term[:-1])
    return frozenset(terms)


@dataclass(frozen=True)
class RecallQuery:
    """What the caller is about to do, and whose facts it may see.

    ``owner_user_id`` is the authenticated canonical user id -- the only owner
    whose facts this query can ever return. Everything else shapes ranking.
    """

    owner_user_id: str
    task_text: str = ""
    persona_hints: tuple[str, ...] = ()
    workspace_id: str = ""
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: Facts below this confidence are not asserted to the task.
    min_confidence: float = 0.0
    #: Highest sensitivity this surface will accept. SENSITIVE requires opt-in.
    max_sensitivity: FactSensitivity = FactSensitivity.PERSONAL
    #: Negative evidence: kinds the current task must not see ("do not surface").
    exclude_kinds: tuple[str, ...] = ()
    #: Cap on returned facts; ``None`` returns every relevant fact, ranked.
    limit: int | None = None

    def __post_init__(self) -> None:
        """A query without a clock or an owner cannot be scored or scoped."""
        if not self.owner_user_id.strip():
            raise ValueError("owner_user_id must be the canonical user id")
        if self.now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0, 1]")


@dataclass(frozen=True)
class ScoredFact:
    """One recalled fact and the relevance score that put it in the context."""

    fact: UserModelFact
    score: float


def _recency(fact: UserModelFact, now: datetime) -> float:
    age_days = max(0.0, (now - fact.last_reinforced).total_seconds() / 86400.0)
    half_lives = age_days / _RECENCY_HALF_LIFE_DAYS
    return float(0.5**half_lives)


def _temporally_valid(fact: UserModelFact, now: datetime) -> bool:
    if fact.valid_from is not None and now < fact.valid_from:
        return False
    return not (fact.valid_until is not None and now >= fact.valid_until)


def _surfaceable(fact: UserModelFact, query: RecallQuery) -> bool:
    """Hard gates: a fact that fails one is never injected, however it scores.

    Only ACTIVE revisions assert anything: UNDER_REVIEW means the model is
    contradicting itself, SUPERSEDED revisions are history, TOMBSTONED
    lineages were deleted by their owner.
    """
    if fact.state is not FactState.ACTIVE:
        return False
    if not fact.reusable:
        return False
    if fact.confidence < query.min_confidence:
        return False
    if fact.kind in query.exclude_kinds:
        return False
    if _SENSITIVITY_RANK[fact.sensitivity] > _SENSITIVITY_RANK[query.max_sensitivity]:
        return False
    return _temporally_valid(fact, query.now)


def score_fact(fact: UserModelFact, query: RecallQuery) -> float:
    """The relevance of one fact to ``query``, or ``0.0`` when it must not surface.

    ``(task + persona + workspace affinity) * confidence * recency``. Persona
    matches either the fact's own relevance hints or its statement terms, so a
    Persona can raise the facts it cares about without touching ownership.
    """
    if not _surfaceable(fact, query):
        return 0.0
    statement_terms = _terms(fact.statement)
    task_terms = _terms(query.task_text)
    persona_terms = _terms(" ".join(query.persona_hints))
    task_overlap = len(task_terms & statement_terms)
    persona_overlap = len(persona_terms & (statement_terms | _terms(" ".join(fact.persona_hints))))
    affinity = (
        1
        if query.workspace_id
        and any(ref.workspace_id == query.workspace_id for ref in fact.evidence)
        else 0
    )
    if task_overlap == 0 and persona_overlap == 0:
        # No topical link at all: not leakage-safe to inject on confidence alone.
        return 0.0
    lexical = float(task_overlap) + 0.5 * float(persona_overlap) + 0.25 * float(affinity)
    return lexical * fact.confidence * _recency(fact, query.now)


async def recall(store: UserModelStore, query: RecallQuery) -> list[ScoredFact]:
    """Rank one owner's facts for the current task; irrelevant facts stay out.

    Reads only ``store.list_for_user(query.owner_user_id)`` -- the durable
    user-model store -- never another Workspace's working graph. The score
    floor is structural, not a magic constant: a fact with no task overlap,
    no persona overlap and no Workspace affinity scores exactly ``0.0`` and
    is dropped, so unrelated tasks receive nothing by default.
    """
    scored = [
        ScoredFact(fact=fact, score=score)
        for fact in await store.list_for_user(query.owner_user_id)
        if (score := score_fact(fact, query)) > 0.0
    ]
    scored.sort(key=lambda item: (-item.score, item.fact.fact_id))
    if query.limit is not None:
        scored = scored[: query.limit]
    return scored
