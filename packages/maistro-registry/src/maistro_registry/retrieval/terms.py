"""Tokenization and corpus-statistical term selection.

The corpus is small (hundreds of documents) and mostly prose, so the whole
retrieval pipeline needs exactly two statistical facts per term — its
document frequency and the total document count. Everything "corpus-aware"
in this package derives from those two numbers:

- BM25's inverse document frequency (`search.py`), and
- rejection of useless query terms: a term that appears in most of the
  corpus — or in none of it — cannot discriminate between documents.
  Keeping "implementation" or "adr" in a query over this corpus does not
  add signal, it lets an everywhere-word flatten every score toward the
  same value.

The rejection is *measured*, not enumerated: there is deliberately no
hand-written stopword table to drift out of sync with what this corpus
actually overuses. A term is useless when `df == 0` (it cannot match
anything) or when its document-frequency share reaches `max_df_share`
(it matches so much that it stops separating documents). Issue #26 calls
this "corpus-statistical rejection of useless terms"; this module is its
single home.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# Tokens are lowercase ASCII alphanumeric runs. "ADR-031" tokenizes to
# ["adr", "031"], so an id typed with or without its dash matches the same
# way. Single characters carry almost no discriminative weight in prose
# and add index noise, so they are dropped ("a", "x"); two-character
# tokens ("ac", "id", "m4") are kept.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

MIN_TOKEN_LENGTH = 2

# Light morphological normalization (Porter step-1a style): strip a single
# trailing "s" from tokens that can bear it, so "migrations" matches
# "migration" and "exports" matches "export". Guarded against the endings
# where the s is structural, not a plural ("access", "status", "genesis").
# "as" is guarded for a corpus-specific reason: this corpus's component
# name "canvas" (and friends like "alias") would otherwise normalize to a
# mangled token that then leaks into user-facing term reports. Length
# floor 4 keeps "as"/"is"/"us" intact.
_PLURAL_KEEP_SUFFIXES = ("ss", "us", "is", "as")


def _normalize(token: str) -> str:
    if len(token) >= 4 and token.endswith("s") and not token.endswith(_PLURAL_KEEP_SUFFIXES):
        return token[:-1]
    return token


# Default ceiling on the document-frequency share a term may reach before
# it is rejected as non-discriminative. Measured on this repo's corpus
# (426 documents: docs/adr + docs/specs + KNOWN-GAPS.md): the corpus's
# own glue words sit far above 0.5 ("spec" 0.73, "adr" 0.85, "the" 0.99,
# "agent" 0.45) while genuinely topic-bearing terms stay far below it
# ("canvas" 0.12, "retrieval" 0.05, "episodic" 0.10). Component names in
# between ("memory" 0.39, "conductor" 0.36) stay *kept* at 0.5 — they
# are real topics, and the always-positive idf already nearly silences
# ubiquitous terms at scoring time, so rejection only needs to remove
# what scoring cannot. Tunable per call — the default is a measurement,
# not a constant of nature.
DEFAULT_MAX_DF_SHARE = 0.5


def tokenize(text: str) -> list[str]:
    """Normalized lowercase tokens of length >= `MIN_TOKEN_LENGTH`.

    Normalization is light by design — trailing-s only. It exists because
    the corpus freely mixes singular and plural ("migration"/"migrations",
    "export"/"exports"), and a lexical baseline that misses on an s is
    missing on the corpus's own spelling habits, not on relevance.
    """
    return [_normalize(t) for t in _TOKEN_RE.findall(text.lower()) if len(t) >= MIN_TOKEN_LENGTH]


@dataclass(frozen=True)
class CorpusStats:
    """Per-term document frequencies over a corpus.

    Built from one *distinct-term set* per document — a term counts once
    per document no matter how often it repeats in it, because df share is
    about coverage ("in how many documents does this word appear at all"),
    not volume.
    """

    total_documents: int
    document_frequency: Mapping[str, int]

    @classmethod
    def from_documents(cls, documents: Iterable[Iterable[str]]) -> CorpusStats:
        """Build stats from an iterable of per-document distinct-term sets."""
        df: dict[str, int] = {}
        total = 0
        for terms in documents:
            total += 1
            for term in set(terms):
                df[term] = df.get(term, 0) + 1
        return cls(total_documents=total, document_frequency=df)

    def df(self, term: str) -> int:
        """Number of documents containing the term (0 if unknown)."""
        return self.document_frequency.get(term, 0)

    def df_share(self, term: str) -> float:
        """Fraction of the corpus containing the term (0.0 for an empty corpus)."""
        if self.total_documents == 0:
            return 0.0
        return self.df(term) / self.total_documents

    def reject_useless(
        self,
        terms: Iterable[str],
        *,
        max_df_share: float = DEFAULT_MAX_DF_SHARE,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Split terms into (kept, rejected) by corpus statistics.

        A term is rejected when the corpus has never seen it (df == 0 — it
        cannot contribute to any score, so keeping it would only obscure
        which terms actually drove a result) or when its df share is at or
        above `max_df_share` (it is corpus glue, not a topic). Kept terms
        preserve first-seen order; rejected terms are reported so a caller
        can show *why* a query underperformed.
        """
        kept: list[str] = []
        rejected: list[str] = []
        for term in terms:
            if self.df(term) == 0 or self.df_share(term) >= max_df_share:
                if term not in rejected:
                    rejected.append(term)
            elif term not in kept:
                kept.append(term)
        return tuple(kept), tuple(rejected)


def idf(stats: CorpusStats, term: str) -> float:
    """BM25 inverse document frequency (the always-positive Okapi variant).

    `ln(1 + (N - df + 0.5) / (df + 0.5))` — the "+1" inside the log keeps
    the value non-negative even for terms present in every document, so a
    ubiquitous term can never contribute a negative score. Rejection
    (`CorpusStats.reject_useless`) handles ubiquity as a *query* concern;
    this floor handles it as a *scoring* concern, which is what keeps an
    index rebuilt with a different rejection threshold comparable.
    """
    n = stats.total_documents
    df = stats.df(term)
    if n == 0 or df == 0:
        return 0.0
    return math.log(1.0 + (n - df + 0.5) / (df + 0.5))
