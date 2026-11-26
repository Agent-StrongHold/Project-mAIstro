"""Index build/persistence and the search pipeline's ordering guarantees.

The properties under test are the ones a consumer actually leans on:
field weights decide *title-vs-body* ordering, corpus statistics decide
which terms may vote, ranking is deterministic, and a loaded index
refuses to impersonate a different corpus state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro_registry.retrieval import (
    IndexVersionError,
    RetrievalSearcher,
    build_index,
    enrich_document,
    load_corpus,
    load_index,
    save_index,
    stale_index_reason,
)
from maistro_registry.retrieval.terms import CorpusStats, idf, tokenize


@pytest.fixture()
def tiny_repo(tmp_path: Path, make_doc: object) -> Path:
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-001-export.md",
        "ADR-001",
        "Export pipeline",
        body="The export step writes bytes. Ordinary filler sentence. Ordinary filler sentence.",
    )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-002-queue.md",
        "ADR-002",
        "Queue discipline",
        body="Export is mentioned once here, but the title is about queues.",
    )
    make_doc(
        tmp_path,
        "docs/specs",
        "SPEC-003-vault.md",
        "SPEC-003",
        "Vault of secrets",
        kind="spec",
        layer="Crypto",
        body="Vault prose. Ordinary filler sentence.",
    )
    return tmp_path


def test_tokenize_normalizes_plural_forms_identically_on_both_sides() -> None:
    assert tokenize("Exports produce Exports") == ["export", "produce", "export"]
    # Structural s-endings survive: the guard exists so "canvas" stays whole.
    assert tokenize("canvas status access") == ["canvas", "status", "access"]
    assert tokenize("migrations tasks runs") == ["migration", "task", "run"]
    # Single characters are dropped.
    assert tokenize("a b cder") == ["cder"]


def test_useless_term_rejection_is_measured_not_enumerated() -> None:
    stats = CorpusStats.from_documents(
        [
            ["export", "pipeline"],
            ["export", "queue"],
            ["export", "vault"],
            ["vault", "secrets"],
        ]
    )
    # "export" is in 3/4 documents: kept below the ceiling, rejected at it.
    # Default ceiling 0.5: "export" covers 0.75 of the corpus, "vault" sits
    # exactly at the ceiling (>= rejects it), "queue" is discriminative,
    # "absent" was never seen.
    kept, rejected = stats.reject_useless(["export", "queue", "vault", "absent"])
    assert kept == ("queue",)
    assert rejected == ("export", "vault", "absent")
    # A looser ceiling keeps the borderline terms and still drops the unseen.
    kept, rejected = stats.reject_useless(["export", "queue", "vault", "absent"], max_df_share=0.8)
    assert kept == ("export", "queue", "vault")
    assert rejected == ("absent",)
    # An empty corpus rejects everything: no corpus, no vote.
    empty = CorpusStats.from_documents([])
    kept, rejected = empty.reject_useless(["anything"])
    assert kept == () and rejected == ("anything",)


def test_df_share_and_idf_refuse_to_invent_signal() -> None:
    """The two scoring inputs stay honest on degenerate inputs: an empty
    corpus and an unseen term contribute zero, not a division error or a
    fabricated weight."""
    empty = CorpusStats.from_documents([])
    assert empty.df_share("anything") == 0.0
    assert idf(empty, "anything") == 0.0

    stats = CorpusStats.from_documents([["export"], ["export", "queue"]])
    assert stats.df_share("export") == 1.0
    # df == 0: a term no document contains scores nothing...
    assert idf(stats, "unseen") == 0.0
    # ...and a term in every document is silenced by the +1 inside the log,
    # never negative.
    assert idf(stats, "export") > 0.0
    assert idf(stats, "queue") > idf(stats, "export")


def test_enrichment_extracts_title_headings_and_slug_keywords(
    tmp_path: Path, make_doc: object
) -> None:
    make_doc(
        tmp_path,
        "docs/specs",
        "SPEC-009-session-search.md",
        "SPEC-009",
        "Session search snippets",
        kind="spec",
        layer="Memory",
        body="## Acceptance criteria\n\nSnippets highlight.\n\nOrdinary prose body.",
    )
    (doc,) = load_corpus(tmp_path)
    enrichment = enrich_document(doc)
    assert "session" in enrichment.title_terms
    assert "search" in enrichment.title_terms
    assert "acceptance" in enrichment.heading_terms
    assert "criteria" in enrichment.heading_terms
    # Filename slug words and the registry id both feed the keyword stream.
    assert "session" in enrichment.keyword_terms and "search" in enrichment.keyword_terms
    assert "spec" in enrichment.keyword_terms and "009" in enrichment.keyword_terms
    assert "memory" in enrichment.keyword_terms
    assert "ordinary" in enrichment.body_terms


def test_title_match_outranks_body_mention(tiny_repo: Path) -> None:
    index = build_index(load_corpus(tiny_repo))
    # Explicit loose ceiling: in this 3-document fixture "export" appears in
    # 2 of 3 documents, which the measured 0.5 default would (correctly)
    # reject; this test is about field weights, not about the ceiling.
    searcher = RetrievalSearcher(index, max_df_share=0.9)
    response = searcher.search("export pipeline", k=2)
    # ADR-001 has both terms in its title; ADR-002 only a body mention.
    assert [r.doc_id for r in response.results] == ["ADR-001", "ADR-002"]
    first, second = response.results
    assert first.score > second.score
    assert set(first.matched_terms) == {"export", "pipeline"}


def test_ubiquitous_term_is_rejected_and_reported(tiny_repo: Path) -> None:
    # "ordinary" appears in 2 of 3 documents; at a 0.5 ceiling it cannot vote.
    index = build_index(load_corpus(tiny_repo))
    searcher = RetrievalSearcher(index, max_df_share=0.5)
    response = searcher.search("ordinary vault", k=3)
    assert "ordinary" in response.rejected_terms
    assert "vault" in response.query_terms
    assert [r.doc_id for r in response.results] == ["SPEC-003"]


def test_ranking_is_deterministic_with_path_tiebreak(tmp_path: Path, make_doc: object) -> None:
    # Two identical twins plus one unrelated document: the twins tie on
    # score, and the tie must resolve by path — identically on every run.
    for name in ("ADR-010-twin-a.md", "ADR-011-twin-b.md"):
        make_doc(
            tmp_path,
            "docs/adr",
            name,
            "ADR-010" if "a.md" in name else "ADR-011",
            "Twin topic",
            body="Identical bodies.",
        )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-012-other.md",
        "ADR-012",
        "Different matter",
        body="Unrelated prose.",
    )
    index = build_index(load_corpus(tmp_path))
    # The twins share both terms (df 2/3), so a loose ceiling lets them vote;
    # the tie itself is the property under test.
    searcher = RetrievalSearcher(index, max_df_share=0.9)
    runs = [[r.path for r in searcher.search("twin topic", k=3).results] for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    assert runs[0][:2] == ["docs/adr/ADR-010-twin-a.md", "docs/adr/ADR-011-twin-b.md"]


def test_index_save_load_roundtrip_preserves_scoring(tiny_repo: Path, tmp_path: Path) -> None:
    docs = load_corpus(tiny_repo)
    index = build_index(docs)
    path = save_index(index, tmp_path / "nested" / "index.json")
    loaded = load_index(path)
    assert loaded.fingerprint == index.fingerprint
    assert loaded.avgdl == pytest.approx(index.avgdl)
    original = RetrievalSearcher(index, max_df_share=0.9).search("export pipeline", k=3)
    restored = RetrievalSearcher(loaded, max_df_share=0.9).search("export pipeline", k=3)
    assert [(r.doc_id, r.score) for r in restored.results] == [
        (r.doc_id, r.score) for r in original.results
    ]


def test_index_refuses_foreign_format_version(tiny_repo: Path, tmp_path: Path) -> None:
    path = save_index(build_index(load_corpus(tiny_repo)), tmp_path / "i.json")
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"format_version": 1', '"format_version": 999'), encoding="utf-8")
    with pytest.raises(IndexVersionError, match="format version"):
        load_index(path)


def test_stale_index_reason_enforces_freshness_against_the_corpus(
    tiny_repo: Path, make_doc: object
) -> None:
    """The fingerprint is a contract, not a label: a saved index whose
    corpus has moved on must be reportable as stale, naming both states,
    while an unchanged corpus stays servable."""
    index = build_index(load_corpus(tiny_repo))
    assert stale_index_reason(index, load_corpus(tiny_repo)) is None

    # Addition leg: a new document is a different corpus state.
    make_doc(
        tiny_repo,
        "docs/adr",
        "ADR-004-extra.md",
        "ADR-004",
        "Extra document",
        body="More prose.",
    )
    reason = stale_index_reason(index, load_corpus(tiny_repo))
    assert reason is not None
    assert index.fingerprint in reason, "the refusal names the index's own state"
    assert "maistro-registry index" in reason, "the refusal names the rebuild command"

    # Content-change leg: edited bytes are stale too, even at the same path.
    refreshed = build_index(load_corpus(tiny_repo))
    path = tiny_repo / "docs/adr/ADR-004-extra.md"
    path.write_text(path.read_text(encoding="utf-8").replace("More prose.", "Changed prose."))
    assert stale_index_reason(refreshed, load_corpus(tiny_repo)) is not None


def test_fingerprint_moves_with_any_corpus_change(tiny_repo: Path, make_doc: object) -> None:
    before = build_index(load_corpus(tiny_repo)).fingerprint
    make_doc(
        tiny_repo,
        "docs/adr",
        "ADR-004-extra.md",
        "ADR-004",
        "Extra document",
        body="More prose.",
    )
    added = build_index(load_corpus(tiny_repo)).fingerprint
    assert before != added

    # Removal is the same contract from the other side: the refreshed
    # index must not still carry the deleted document's terms.
    (tiny_repo / "docs/adr/ADR-004-extra.md").unlink()
    index_after_removal = build_index(load_corpus(tiny_repo))
    assert index_after_removal.fingerprint == before
    assert "ADR-004" not in {d.document.doc_id for d in index_after_removal.documents}, (
        "a removed source must not survive in a rebuilt index"
    )
