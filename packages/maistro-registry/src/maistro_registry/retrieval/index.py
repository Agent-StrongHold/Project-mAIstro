"""Offline enrichment and the lexical (BM25) index.

Two jobs, both done once per corpus instead of once per query:

1. **Offline document enrichment.** For every `CorpusDocument`, extract
   the term streams that prose alone hides: the title, the markdown
   headings, the registry id, and the filename slug. A spec titled
   "Hybrid BM25 + vector memory retrieval ranking" says "BM25" in its
   title and "ranking" in its slug; the body repeats both, but a query
   should not need the body to repeat them before the document ranks.
   Enrichment assigns each stream a weight (title > headings/keywords >
   body) so *where* a term appears changes how much it counts — this is
   a field-weighted BM25 approximation, not a second scoring path.

2. **The index itself**: per-document weighted term frequencies, corpus
   statistics (`terms.CorpusStats`), the mean document length BM25
   normalizes by, and a `fingerprint` over (path, version) pairs that
   pins which corpus state an index was built from. Saved indexes carry
   the fingerprint and format version; loading one built from a different
   corpus state raises `IndexVersionError` instead of silently scoring
   against stale provenance.

No external deps: tokenization and statistics only (`engine#ADR-039`
substrate posture — retrieval stays dependency-free until measured
quality says otherwise, which is the whole point of issue #26).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maistro_registry.retrieval.corpus import CorpusDocument
from maistro_registry.retrieval.terms import CorpusStats, tokenize

# Bumped on any breaking change to the serialized shape; `load_index`
# refuses files with a different version rather than guessing.
INDEX_FORMAT_VERSION = 1

# Field weights for enrichment. Title matches are the strongest "this
# document is about the query" signal this corpus has; headings are the
# document's own table of contents; the id/slug/layer keyword stream
# catches registry-style addressing ("SPEC-243", "memory") that prose
# spells differently. Body is the 1.0 baseline every other weight is
# relative to.
TITLE_WEIGHT = 3.0
HEADING_WEIGHT = 2.0
KEYWORD_WEIGHT = 2.0
BODY_WEIGHT = 1.0

# Okapi defaults; exposed on the index so a rebuild reproduces scoring.
DEFAULT_K1 = 1.5
DEFAULT_B = 0.75

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class DocumentEnrichment:
    """The offline-extracted term streams for one document."""

    title_terms: tuple[str, ...]
    heading_terms: tuple[str, ...]
    keyword_terms: tuple[str, ...]
    body_terms: tuple[str, ...]

    @property
    def all_terms(self) -> tuple[str, ...]:
        return self.title_terms + self.heading_terms + self.keyword_terms + self.body_terms


@dataclass(frozen=True)
class IndexedDocument:
    """One document's weighted term frequencies and enriched length.

    `term_frequencies` values are *weighted* counts (body occurrence =
    1.0, heading = 2.0, ...), and `length` is their sum — BM25's
    document-length normalization then measures enriched mass, which is
    the mass the score actually uses.
    """

    document: CorpusDocument
    term_frequencies: dict[str, float]

    @property
    def length(self) -> float:
        return sum(self.term_frequencies.values())


def slug_keyword_terms(document: CorpusDocument) -> tuple[str, ...]:
    """Keyword stream: filename slug words, registry id, and layer.

    `ADR-048-session-search.md` contributes "session search adr 048";
    front-matter `layer: Memory` contributes "memory". These are the
    terms a human actually types when addressing the corpus.
    """
    terms: list[str] = []
    stem = Path(document.path).stem
    # Strip the id prefix ("ADR-048", "SPEC-062126-757a") from the slug.
    slug = re.sub(r"^(ADR|SPEC)-[0-9a-z-]+?-", "", stem, count=1) if "-" in stem else stem
    terms.extend(tokenize(slug))
    terms.extend(tokenize(document.doc_id))
    if document.layer:
        terms.extend(tokenize(document.layer))
    return tuple(terms)


def enrich_document(document: CorpusDocument) -> DocumentEnrichment:
    """Extract the weighted term streams for one document."""
    return DocumentEnrichment(
        title_terms=tuple(tokenize(document.title)),
        heading_terms=tuple(tokenize("\n".join(_HEADING_RE.findall(document.body)))),
        keyword_terms=slug_keyword_terms(document),
        body_terms=tuple(tokenize(document.body)),
    )


@dataclass(frozen=True)
class RetrievalIndex:
    """A built, self-describing lexical index over one corpus state."""

    documents: tuple[IndexedDocument, ...]
    stats: CorpusStats
    avgdl: float
    fingerprint: str
    k1: float
    b: float

    @property
    def document_count(self) -> int:
        return len(self.documents)


def corpus_fingerprint(documents: list[CorpusDocument]) -> str:
    """Short hash pinning the exact (path, version) pairs of a corpus build."""
    material = "\n".join(sorted(f"{d.path}:{d.version}" for d in documents))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def build_index(
    documents: list[CorpusDocument],
    *,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> RetrievalIndex:
    """Enrich every document and assemble the index plus corpus statistics."""
    indexed: list[IndexedDocument] = []
    for document in documents:
        enrichment = enrich_document(document)
        tf: dict[str, float] = {}
        for term in enrichment.body_terms:
            tf[term] = tf.get(term, 0.0) + BODY_WEIGHT
        for term in enrichment.heading_terms:
            tf[term] = tf.get(term, 0.0) + HEADING_WEIGHT
        for term in enrichment.keyword_terms:
            tf[term] = tf.get(term, 0.0) + KEYWORD_WEIGHT
        for term in enrichment.title_terms:
            tf[term] = tf.get(term, 0.0) + TITLE_WEIGHT
        indexed.append(IndexedDocument(document=document, term_frequencies=tf))

    stats = CorpusStats.from_documents(enrich_document(d).all_terms for d in documents)
    lengths = [doc.length for doc in indexed]
    avgdl = (sum(lengths) / len(lengths)) if lengths else 0.0
    return RetrievalIndex(
        documents=tuple(indexed),
        stats=stats,
        avgdl=avgdl,
        fingerprint=corpus_fingerprint(documents),
        k1=k1,
        b=b,
    )


def index_to_dict(index: RetrievalIndex) -> dict[str, Any]:
    """Serialize an index (with manifest) to a JSON-safe dict."""
    return {
        "format_version": INDEX_FORMAT_VERSION,
        "fingerprint": index.fingerprint,
        "k1": index.k1,
        "b": index.b,
        "avgdl": index.avgdl,
        "document_count": index.document_count,
        "stats": {
            "total_documents": index.stats.total_documents,
            "document_frequency": dict(sorted(index.stats.document_frequency.items())),
        },
        "documents": [
            {
                "doc": {
                    "doc_id": d.document.doc_id,
                    "title": d.document.title,
                    "kind": d.document.kind,
                    "status": d.document.status,
                    "layer": d.document.layer,
                    "path": d.document.path,
                    "version": d.document.version,
                    "section": d.document.section,
                },
                "term_frequencies": dict(
                    sorted(
                        d.term_frequencies.items(),
                        key=lambda kv: (-kv[1], kv[0]),
                    )
                ),
            }
            for d in index.documents
        ],
    }


class IndexVersionError(RuntimeError):
    """A saved index cannot be trusted for this corpus or this code."""


def index_from_dict(data: dict[str, Any]) -> RetrievalIndex:
    """Rebuild an index from `index_to_dict` output, refusing mismatches.

    Bodies are not serialized: scoring needs only term frequencies and
    provenance, and results surface the path so callers can read the
    document itself. A loaded index therefore stays small enough to ship
    as an artifact.
    """
    fmt = data.get("format_version")
    if fmt != INDEX_FORMAT_VERSION:
        raise IndexVersionError(
            f"index format version {fmt!r} not supported (expected {INDEX_FORMAT_VERSION})"
        )
    documents = tuple(
        IndexedDocument(
            document=CorpusDocument(
                doc_id=d["doc"]["doc_id"],
                title=d["doc"]["title"],
                kind=d["doc"]["kind"],
                status=d["doc"]["status"],
                layer=d["doc"]["layer"],
                path=d["doc"]["path"],
                version=d["doc"]["version"],
                body="",
                front_matter=None,
                section=d["doc"]["section"],
            ),
            term_frequencies={t: float(v) for t, v in d["term_frequencies"].items()},
        )
        for d in data["documents"]
    )
    stats = CorpusStats(
        total_documents=int(data["stats"]["total_documents"]),
        document_frequency={t: int(v) for t, v in data["stats"]["document_frequency"].items()},
    )
    return RetrievalIndex(
        documents=documents,
        stats=stats,
        avgdl=float(data["avgdl"]),
        fingerprint=str(data["fingerprint"]),
        k1=float(data["k1"]),
        b=float(data["b"]),
    )


def save_index(index: RetrievalIndex, path: Path) -> Path:
    """Write the index as deterministic JSON (sorted keys, fixed indent)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(index_to_dict(index), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_index(path: Path) -> RetrievalIndex:
    """Load a saved index, raising `IndexVersionError` on shape mismatch."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise IndexVersionError(f"{path}: index file must be a JSON object")
    return index_from_dict(data)
