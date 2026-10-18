"""Measured retrieval quality: golden queries, IR metrics, evaluation.

"Measurable before more infrastructure" is issue #26's point: this module
is where retrieval quality stops being an impression and becomes numbers
that a test (and the `maistro-registry eval` CLI command) can hold a line
with.

Golden sets are graded, not binary: each expected document carries a
relevance grade — 3 = directly about the query, 2 = strongly relevant, 1 =
related context. Grades feed nDCG; the binary cut for Recall@k and MRR is
`GRADE_RELEVANT` (grade >= 2), because "found something merely related in
rank 1" must not read as a hit.

Metrics, over one query's ranked ids:

- `recall_at_k` — share of *relevant* documents present in the top k.
  The "did we find the things" measure.
- `mrr` — 1 / rank of the first relevant document (0 if none in top k).
  The "how fast can a human stop scrolling" measure.
- `ndcg_at_k` — graded, position-discounted gain. The only one of the
  three that rewards ordering *among* relevant documents.

`evaluate` runs a search function over a golden set and returns a
`QualityReport` with per-query cases plus aggregates; the CLI renders it
and can fail a threshold (`--min-mrr`, `--min-recall`), which is how a
retrieval regression becomes a red build instead of a vibe.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maistro_registry.retrieval.search import SearchResponse

# A document counts as "relevant" for the binary metrics at this grade or
# above. Grade 1 records useful-but-not-on-point context so nDCG can still
# see it without letting it satisfy recall.
GRADE_RELEVANT = 2

GRADE_DIRECT = 3
GRADE_RELATED = 1


@dataclass(frozen=True)
class GoldenQuery:
    """One evaluation query with its graded expected documents.

    `relevant` maps doc_id -> grade. Doc ids are registry ids
    ("ADR-048", "SPEC-243") or known-gap section ids
    ("KNOWN-GAPS#task-queue-persistence") — the same ids provenance
    carries, so a failure names the miss.
    """

    query: str
    relevant: Mapping[str, int]
    note: str = ""


@dataclass(frozen=True)
class QueryEvaluation:
    """One query's outcome: ranking, per-metric values, and what matched."""

    query: str
    ranked_ids: tuple[str, ...]
    relevant_ids: frozenset[str]
    recall: float
    mrr: float
    ndcg: float
    matched_relevant: tuple[str, ...]


@dataclass(frozen=True)
class QualityReport:
    """Aggregate retrieval quality over a golden set."""

    k: int
    cases: tuple[QueryEvaluation, ...]
    mean_recall: float
    mean_mrr: float
    mean_ndcg: float

    def render(self) -> str:
        lines = [
            f"retrieval quality over {len(self.cases)} golden queries (k={self.k})",
            f"  recall@{self.k}: {self.mean_recall:.4f}",
            f"  mrr:          {self.mean_mrr:.4f}",
            f"  ndcg@{self.k}:  {self.mean_ndcg:.4f}",
            "",
        ]
        for case in self.cases:
            status = "ok " if case.mrr > 0.0 else "MISS"
            lines.append(
                f"  [{status}] {case.query!r}: mrr={case.mrr:.3f} "
                f"recall={case.recall:.3f} ndcg={case.ndcg:.3f}"
            )
            if case.relevant_ids:
                missed = sorted(case.relevant_ids - set(case.ranked_ids))
                if missed:
                    lines.append(f"         missed: {', '.join(missed)}")
        return "\n".join(lines)


def recall_at_k(ranked_ids: Sequence[str], relevant: Mapping[str, int], k: int) -> float:
    """Share of binary-relevant documents present in the top k."""
    relevant_ids = {doc for doc, grade in relevant.items() if grade >= GRADE_RELEVANT}
    if not relevant_ids:
        return 0.0
    found = sum(1 for doc_id in ranked_ids[:k] if doc_id in relevant_ids)
    return found / len(relevant_ids)


def mrr(ranked_ids: Sequence[str], relevant: Mapping[str, int]) -> float:
    """Reciprocal rank of the first binary-relevant document."""
    relevant_ids = {doc for doc, grade in relevant.items() if grade >= GRADE_RELEVANT}
    for rank, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[str], relevant: Mapping[str, int], k: int) -> float:
    """Graded nDCG@k (linear gain = grade, log2 position discount)."""
    gains = [float(relevant.get(doc_id, 0)) for doc_id in ranked_ids[:k]]
    dcg = math.fsum(gain / math.log2(position + 1) for position, gain in enumerate(gains, 1))
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = math.fsum(
        float(grade) / math.log2(position + 1) for position, grade in enumerate(ideal, 1)
    )
    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


def _parse_golden_entry(path: Path, entry: Any) -> GoldenQuery:
    """Validate one golden-set entry; raise ValueError naming `path`."""
    if not isinstance(entry, dict) or not isinstance(entry.get("query"), str):
        raise ValueError(f"{path}: each entry needs a string 'query'")
    relevant = entry.get("relevant")
    if not isinstance(relevant, dict) or not all(
        isinstance(doc, str) and isinstance(grade, int) for doc, grade in relevant.items()
    ):
        raise ValueError(f"{path}: 'relevant' must map doc-id strings to int grades")
    # Grades are the named scale, not free integers: RELATED is the
    # floor (anything lower could not be told apart from noise) and
    # DIRECT the ceiling (nothing is more on-point than on-point).
    if not all(GRADE_RELATED <= grade <= GRADE_DIRECT for grade in relevant.values()):
        raise ValueError(
            f"{path}: grades must be in {GRADE_RELATED}..{GRADE_DIRECT} "
            f"(RELATED..DIRECT); got {sorted(relevant.values())}"
        )
    note = entry.get("note", "")
    return GoldenQuery(
        query=entry["query"],
        relevant=dict(relevant),
        note=note if isinstance(note, str) else "",
    )


def load_golden(path: Path) -> list[GoldenQuery]:
    """Load a golden set: JSON array of {query, relevant, note?} objects."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: golden set must be a JSON array")
    return [_parse_golden_entry(path, entry) for entry in data]


def _evaluate_case(
    search_fn: Callable[[str, int], SearchResponse],
    golden_query: GoldenQuery,
    k: int,
) -> QueryEvaluation:
    """One golden query through `search_fn(query, k)`, fully measured.

    The ranking is reduced to first occurrences of each doc id before any
    metric sees it. Duplicate identity is a real, addressable corpus
    state (two files claiming one registry id), so a searcher may return
    the same id twice — but the golden set is keyed by doc id, and one
    relevant document found twice is still one document found. Without
    the reduction, recall and nDCG count the second occurrence as a new
    hit and report shares above 1.0, which is not a measurement of
    anything.
    """
    response = search_fn(golden_query.query, k)
    ranked_ids = tuple(dict.fromkeys(result.doc_id for result in response.results))
    relevant_ids = frozenset(
        doc for doc, grade in golden_query.relevant.items() if grade >= GRADE_RELEVANT
    )
    return QueryEvaluation(
        query=golden_query.query,
        ranked_ids=ranked_ids,
        relevant_ids=relevant_ids,
        recall=recall_at_k(ranked_ids, golden_query.relevant, k),
        mrr=mrr(ranked_ids, golden_query.relevant),
        ndcg=ndcg_at_k(ranked_ids, golden_query.relevant, k),
        matched_relevant=tuple(doc for doc in ranked_ids if doc in relevant_ids),
    )


def evaluate(
    search_fn: Callable[[str, int], SearchResponse],
    golden: Sequence[GoldenQuery],
    *,
    k: int = 10,
) -> QualityReport:
    """Run every golden query through `search_fn(query, k)` and measure.

    `search_fn` takes (query, k) and returns a `SearchResponse`, so both a
    live `RetrievalSearcher` and a test double can drive the same
    measurement.
    """
    cases = [_evaluate_case(search_fn, golden_query, k) for golden_query in golden]
    n = len(cases)
    return QualityReport(
        k=k,
        cases=tuple(cases),
        mean_recall=sum(c.recall for c in cases) / n if n else 0.0,
        mean_mrr=sum(c.mrr for c in cases) / n if n else 0.0,
        mean_ndcg=sum(c.ndcg for c in cases) / n if n else 0.0,
    )


def report_to_dict(report: QualityReport) -> dict[str, Any]:
    """JSON-safe report for artifacts and threshold tooling."""
    return {
        "k": report.k,
        "mean_recall": report.mean_recall,
        "mean_mrr": report.mean_mrr,
        "mean_ndcg": report.mean_ndcg,
        "cases": [
            {
                "query": c.query,
                "ranked_ids": list(c.ranked_ids),
                "relevant_ids": sorted(c.relevant_ids),
                "matched_relevant": list(c.matched_relevant),
                "recall": c.recall,
                "mrr": c.mrr,
                "ndcg": c.ndcg,
            }
            for c in report.cases
        ],
    }
