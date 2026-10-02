"""Measured retrieval quality: metric math, golden-set shape, and the
real-corpus quality line.

The last test is the acceptance point of issue #26: the shipped golden
set is evaluated against the actual repository corpus, and the measured
numbers must stay above the recorded floor. If this test fails, either
retrieval regressed or the corpus moved — and in both cases the right
response is to look at `maistro-registry eval`'s per-query report, not
to lower the floor silently.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from maistro_registry.retrieval import (
    RetrievalSearcher,
    build_index,
    evaluate,
    load_corpus,
    load_golden,
)
from maistro_registry.retrieval.corpus import CorpusDocument
from maistro_registry.retrieval.expand import NoExpansion
from maistro_registry.retrieval.index import IndexedDocument
from maistro_registry.retrieval.quality import (
    GRADE_RELEVANT,
    GoldenQuery,
    mrr,
    ndcg_at_k,
    recall_at_k,
    report_to_dict,
)
from maistro_registry.retrieval.search import SearchResponse, SearchResult

# The shipped golden set, evaluated against the real repository corpus.
REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "maistro_registry"
    / "retrieval"
    / "golden_queries.json"
)

# The quality floor this change records (issue #26's "measured retrieval
# quality"). Measured at authoring time: MRR 1.0, recall@10 1.0, nDCG@10
# 0.971 over the 20 golden queries. Headroom is deliberate headroom, not
# slack to burn: a drop below these numbers is a regression to explain.
MIN_MEAN_MRR = 0.90
MIN_MEAN_RECALL = 0.90


def test_recall_mrr_ndcg_exact_math() -> None:
    relevant = {"A": 3, "B": 2, "C": 1}
    ranked = ["X", "A", "B"]
    # Recall: 2 of the 2 binary-relevant docs found in top 3.
    assert recall_at_k(ranked, relevant, 3) == 1.0
    assert recall_at_k(["X", "B"], relevant, 2) == 0.5
    # Grade-1 docs are context, not hits.
    assert recall_at_k(["C"], relevant, 1) == 0.0
    # MRR: first relevant at rank 2.
    assert mrr(ranked, relevant) == 0.5
    assert mrr(["A"], relevant) == 1.0
    assert mrr(["X", "Y"], relevant) == 0.0
    # nDCG@3: DCG = 0/log2(2) + 3/log2(3) + 2/log2(4); the ideal ranking is
    # every graded doc desc (3, 2, 1) at the discounted positions.
    dcg = 3 / math.log2(3) + 2 / math.log2(4)
    idcg = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k(ranked, relevant, 3) == pytest.approx(dcg / idcg)


def test_metrics_handle_absent_and_edge_grades() -> None:
    assert recall_at_k([], {"A": 3}, 5) == 0.0
    assert mrr([], {"A": 3}) == 0.0
    # No binary-relevant doc at all: metrics say 0, not a crash.
    assert recall_at_k(["A"], {"A": 1}, 1) == 0.0
    assert mrr(["A"], {"A": 1}) == 0.0
    assert ndcg_at_k(["A"], {"A": 1}, 1) == 1.0
    assert ndcg_at_k(["A"], {}, 1) == 0.0
    # GRADE_RELEVANT is the binary cut, on purpose.
    assert GRADE_RELEVANT == 2


def _fake_indexed(doc_id: str) -> IndexedDocument:
    """A minimal IndexedDocument so `evaluate` can read ranked ids."""
    return IndexedDocument(
        document=CorpusDocument(
            doc_id=doc_id,
            title="t",
            kind="adr",
            status="Accepted",
            layer=None,
            path=f"{doc_id}.md",
            version="v",
            body="",
            front_matter=None,
        ),
        term_frequencies={},
    )


def test_load_golden_validates_shape(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    path.write_text(
        '[{"query": "q", "relevant": {"ADR-001": 3}, "note": "n"}]',
        encoding="utf-8",
    )
    golden = load_golden(path)
    assert golden == [GoldenQuery(query="q", relevant={"ADR-001": 3}, note="n")]

    bad = tmp_path / "bad.json"
    bad.write_text('[{"relevant": {"A": 3}}]', encoding="utf-8")
    with pytest.raises(ValueError, match="query"):
        load_golden(bad)

    bad_grades = tmp_path / "bad-grades.json"
    bad_grades.write_text('[{"query": "q", "relevant": {"A": "high"}}]', encoding="utf-8")
    with pytest.raises(ValueError, match="relevant"):
        load_golden(bad_grades)

    out_of_range = tmp_path / "range.json"
    out_of_range.write_text('[{"query": "q", "relevant": {"A": 4}}]', encoding="utf-8")
    with pytest.raises(ValueError, match=r"grades must be in 1\.\.3"):
        load_golden(out_of_range)


def test_evaluate_aggregates_and_reports_misses() -> None:
    golden = [
        GoldenQuery(query="good", relevant={"ADR-001": 3}),
        GoldenQuery(query="bad", relevant={"ADR-009": 3}),
    ]

    def search_fn(query: str, k: int) -> SearchResponse:
        cutoff = k  # evaluate always passes the configured k through
        doc_id = "ADR-001" if query == "good" else "ADR-002"
        return SearchResponse(
            query=query,
            results=(
                SearchResult(
                    document=_fake_indexed(doc_id),
                    score=1.0,
                    matched_terms=("term",),
                ),
            ),
            query_terms=(query,),
            rejected_terms=(),
            k=cutoff,
        )

    report = evaluate(search_fn, golden, k=10)
    assert report.mean_mrr == 0.5  # first query hits at rank 1, second misses
    assert report.mean_recall == 0.5
    assert report.cases[1].relevant_ids == frozenset({"ADR-009"})
    rendered = report.render()
    assert "MISS" in rendered and "missed: ADR-009" in rendered
    as_dict = report_to_dict(report)
    assert as_dict["mean_mrr"] == 0.5 and len(as_dict["cases"]) == 2
    # The per-case audit trail survives serialization: which relevant docs
    # matched (and, by absence, which were missed) is exactly what an
    # artifact consumer needs to debug a MISS.
    assert as_dict["cases"][0]["matched_relevant"] == ["ADR-001"]
    assert as_dict["cases"][1]["matched_relevant"] == []


def test_shipped_golden_set_is_wellformed() -> None:
    golden = load_golden(GOLDEN_FILE)
    assert len(golden) >= 20
    for g in golden:
        assert g.query and g.relevant
        assert all(1 <= grade <= 3 for grade in g.relevant.values())
        assert g.note, "every golden query must say what it exercises"


def test_real_corpus_meets_the_recorded_quality_floor() -> None:
    golden = load_golden(GOLDEN_FILE)
    index = build_index(load_corpus(REPO_ROOT))
    searcher = RetrievalSearcher(index)
    report = evaluate(lambda q, k: searcher.search(q, k=k, expander=NoExpansion()), golden, k=10)
    print(report.render())
    assert report.mean_mrr >= MIN_MEAN_MRR, f"MRR {report.mean_mrr:.4f} < {MIN_MEAN_MRR}"
    assert report.mean_recall >= MIN_MEAN_RECALL, (
        f"recall@10 {report.mean_recall:.4f} < {MIN_MEAN_RECALL}"
    )
    # Every golden query must retrieve something at all.
    assert all(case.ranked_ids for case in report.cases)
