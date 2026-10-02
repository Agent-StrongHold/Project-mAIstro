"""Corpus-aware architectural retrieval for ADR/spec/known-gap documents.

Implements issue #26 (EPIC M4-F): make ADR/spec/AC/incident/known-gap
retrieval *measurable and corpus-aware* before reaching for vector
infrastructure. The pipeline, each stage in its own module:

- `corpus` — provenance-carrying documents (ADR/spec front matter plus
  KNOWN-GAPS.md split into per-gap retrieval units), with content
  versions retained.
- `terms` — tokenization and corpus statistics: the measured,
  not-enumerated, rejection of useless query terms.
- `index` — offline document enrichment (title/headings/id/slug/layer
  streams with field weights) and the BM25 index with a corpus
  fingerprint, serializable as a JSON artifact.
- `expand` — optional LLM query expansion over an OpenAI-compatible
  endpoint; failures are surfaced, never fabricated away.
- `search` — the pipeline: tokenize, reject, expand, BM25, deterministic
  rank, provenance-carrying results.
- `quality` — graded golden queries, recall/MRR/nDCG, threshold-capable
  evaluation so retrieval regressions are measurable.

No new external dependencies (pyyaml/pydantic/httpx were already here):
`engine#ADR-039` substrate posture, and the epic's own premise — a
lexical baseline that is actually measured first.
"""

from __future__ import annotations

from maistro_registry.retrieval.corpus import (
    CorpusDocument,
    content_version,
    load_corpus,
)
from maistro_registry.retrieval.expand import (
    ExpansionError,
    NoExpansion,
    OpenAICompatExpander,
    QueryExpander,
)
from maistro_registry.retrieval.index import (
    IndexVersionError,
    RetrievalIndex,
    build_index,
    enrich_document,
    load_index,
    save_index,
)
from maistro_registry.retrieval.quality import (
    GoldenQuery,
    QualityReport,
    evaluate,
    load_golden,
    mrr,
    ndcg_at_k,
    recall_at_k,
    report_to_dict,
)
from maistro_registry.retrieval.search import (
    RetrievalSearcher,
    SearchResponse,
    SearchResult,
)
from maistro_registry.retrieval.terms import CorpusStats, tokenize

__all__ = [
    "CorpusDocument",
    "CorpusStats",
    "ExpansionError",
    "GoldenQuery",
    "IndexVersionError",
    "NoExpansion",
    "OpenAICompatExpander",
    "QualityReport",
    "QueryExpander",
    "RetrievalIndex",
    "RetrievalSearcher",
    "SearchResponse",
    "SearchResult",
    "build_index",
    "content_version",
    "enrich_document",
    "evaluate",
    "load_corpus",
    "load_golden",
    "load_index",
    "mrr",
    "ndcg_at_k",
    "recall_at_k",
    "report_to_dict",
    "save_index",
    "tokenize",
]
