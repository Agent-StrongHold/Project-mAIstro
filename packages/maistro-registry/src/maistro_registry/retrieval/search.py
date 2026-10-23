"""The search pipeline: tokenize, reject useless terms, expand, BM25, rank.

Order matters and is the pipeline's whole design:

1. **Tokenize** the query exactly as documents were tokenized — a
   tokenizer mismatch is the classic way lexical search silently stops
   working.
2. **Reject useless terms** with corpus statistics (`terms.CorpusStats`):
   terms the corpus has never seen, and terms so ubiquitous they cannot
   discriminate, are dropped and *reported back* in the response. This is
   the corpus refusing to let noise words vote.
3. **Expand** (optional LLM step, `expand.py`): candidate terms join the
   kept query terms and then face the *same* corpus-statistical filter —
   the model proposes, the corpus disposes. An expansion failure is
   recorded (`expansion_skipped` + the error) and retrieval proceeds
   lexical-only; it never fails the search.
4. **Score** with Okapi BM25 over field-weighted term frequencies
   (`index.py`): `idf * tf*(k1+1) / (tf + k1*(1 - b + b*dl/avgdl))`,
   summed over kept terms.
5. **Rank** descending, ties broken by path so the same corpus state
   always yields the same ranking — golden-set metrics are only
   meaningful if ranking is deterministic.

Every result carries the document's full provenance (`CorpusDocument`:
path, id, status, content version) and the terms that actually matched,
so a caller can show not just *what* ranked but *why*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from maistro_registry.retrieval.expand import ExpansionError, QueryExpander
from maistro_registry.retrieval.index import IndexedDocument, RetrievalIndex
from maistro_registry.retrieval.terms import DEFAULT_MAX_DF_SHARE, tokenize


@dataclass(frozen=True)
class SearchResult:
    """One ranked document: provenance, score, and the terms that earned it."""

    document: IndexedDocument
    score: float
    matched_terms: tuple[str, ...]

    @property
    def doc_id(self) -> str:
        return self.document.document.doc_id

    @property
    def path(self) -> str:
        return self.document.document.path

    @property
    def title(self) -> str:
        return self.document.document.title

    def render(self) -> str:
        """One human-readable result line with provenance attached."""
        doc = self.document.document
        status = doc.status if doc.status is not None else "?"
        return (
            f"{self.score:7.4f}  {doc.doc_id} [{status}] ({doc.version}) {doc.path} — {doc.title}"
        )


@dataclass(frozen=True)
class SearchResponse:
    """Everything one query produced, including the pipeline's own audit trail."""

    query: str
    results: tuple[SearchResult, ...]
    query_terms: tuple[str, ...]
    rejected_terms: tuple[str, ...]
    expanded_terms: tuple[str, ...] = ()
    expansion_skipped: bool = False
    expansion_error: str | None = None
    k: int = field(default=10)


class RetrievalSearcher:
    """BM25 search over a `RetrievalIndex` with corpus-aware term filtering."""

    def __init__(
        self,
        index: RetrievalIndex,
        *,
        max_df_share: float = DEFAULT_MAX_DF_SHARE,
    ) -> None:
        self._index = index
        self._max_df_share = max_df_share

    @property
    def index(self) -> RetrievalIndex:
        return self._index

    def search(
        self,
        query: str,
        *,
        k: int = 10,
        expander: QueryExpander | None = None,
    ) -> SearchResponse:
        kept, rejected = self._index.stats.reject_useless(
            tokenize(query), max_df_share=self._max_df_share
        )
        query_terms = tuple(dict.fromkeys(kept))

        expanded_terms: list[str] = []
        expansion_skipped = False
        expansion_error: str | None = None
        if expander is not None:
            try:
                candidates = expander.expand(query)
            except ExpansionError as exc:
                expansion_skipped = True
                expansion_error = str(exc)
            else:
                # Expansion terms face the same corpus-statistical filter as
                # the query itself, and go through the same tokenizer first —
                # models return phrases ("queue recovery") and inflected
                # forms, and an untokenized phrase would never equal a
                # corpus token, silently discarding useful expansions.
                # Already-kept terms are not double-counted.
                candidate_terms: list[str] = []
                for candidate in candidates:
                    candidate_terms.extend(tokenize(candidate))
                e_kept, e_rejected = self._index.stats.reject_useless(
                    candidate_terms, max_df_share=self._max_df_share
                )
                rejected = tuple(dict.fromkeys(rejected + e_rejected))
                expanded_terms = [t for t in e_kept if t not in query_terms]

        hits: list[tuple[IndexedDocument, float, tuple[str, ...]]] = []
        for doc in self._index.documents:
            score = self._score(doc, query_terms, expanded_terms)
            if score > 0.0:
                hits.append((doc, score, self._matched(doc, query_terms, expanded_terms)))
        # Deterministic order: score descending, then path ascending. Path as
        # the tiebreaker is what makes golden-set metrics reproducible.
        hits.sort(key=lambda h: (-h[1], h[0].document.path))
        results = tuple(
            SearchResult(document=doc, score=score, matched_terms=matched)
            for doc, score, matched in hits[:k]
        )
        return SearchResponse(
            query=query,
            results=results,
            query_terms=query_terms,
            rejected_terms=rejected,
            expanded_terms=tuple(expanded_terms),
            expansion_skipped=expansion_skipped,
            expansion_error=expansion_error,
            k=k,
        )

    def _matched(
        self,
        doc: IndexedDocument,
        query_terms: tuple[str, ...],
        expanded_terms: list[str],
    ) -> tuple[str, ...]:
        return tuple(t for t in (*query_terms, *expanded_terms) if t in doc.term_frequencies)

    def _score(
        self,
        doc: IndexedDocument,
        query_terms: tuple[str, ...],
        expanded_terms: list[str],
    ) -> float:
        """Okapi BM25 over the document's weighted term frequencies."""
        dl = doc.length
        avgdl = self._index.avgdl
        if avgdl <= 0.0:
            return 0.0
        k1, b = self._index.k1, self._index.b
        score = 0.0
        for term in (*query_terms, *expanded_terms):
            tf = doc.term_frequencies.get(term)
            if not tf:
                continue
            idf = _idf(self._index, term)
            score += idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl))
        return score


def _idf(index: RetrievalIndex, term: str) -> float:
    """Okapi idf with the always-positive Lucene variant (see terms.idf)."""
    n = index.stats.total_documents
    df = index.stats.df(term)
    if n == 0 or df == 0:
        return 0.0
    return math.log(1.0 + (n - df + 0.5) / (df + 0.5))
