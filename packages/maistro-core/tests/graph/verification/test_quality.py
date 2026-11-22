"""Tests for the deterministic summarize-quality heuristic (epic M4-I).

The score is the escalation ladder's production input, so its contract is
narrow and load-bearing: deterministic, bounded, zero for an empty summary,
and full credit only when a summary both compresses its source and keeps the
source's salient words. Cases isolate one component at a time on purpose —
a heuristic test that mixes components fails for the wrong reason.
"""

from __future__ import annotations

import random

from maistro.graph.verification.quality import summarize_quality

#: A source whose information lives in five salient words surrounded by
#: filler, so "keeps what mattered" and "actually compressed" are separately
#: constructible.
_SALIENT = "payments migration canary latency dashboard"
_FILLER = " ".join(["the and of to in on it"] * 20)
_SOURCE = f"{_SALIENT} {_FILLER}"


def test_empty_summary_scores_zero() -> None:
    assert summarize_quality(_SOURCE, "") == 0.0
    assert summarize_quality(_SOURCE, "   ") == 0.0


def test_keeps_salient_words_and_compresses_scores_high() -> None:
    summary = f"{_SALIENT} shipped"
    assert summarize_quality(_SOURCE, summary) >= 0.9


def test_verbatim_copy_scores_no_compression_credit() -> None:
    # Perfect coverage, zero compression: a copy is not a summary.
    assert summarize_quality(_SOURCE, _SOURCE) < 0.6


def test_near_copy_loses_almost_all_compression_credit() -> None:
    # Dropping only the trailing filler word keeps every salient token but
    # stays a near-copy in length.
    near_copy = _SOURCE[: -len(" it")]
    assert summarize_quality(_SOURCE, near_copy) < 0.6


def test_compresses_but_drops_every_salient_word_scores_half_at_most() -> None:
    summary = "stuff happened somehow somewhere sometime"
    assert summarize_quality(_SOURCE, summary) <= 0.5


def test_near_empty_summary_scores_near_zero() -> None:
    assert summarize_quality(_SOURCE, ".") < 0.1


def test_empty_source_with_contentful_summary_is_not_punished_on_shape() -> None:
    # Coverage carries the empty case; compression must not zero it out.
    assert summarize_quality("", "a reasonable answer") == 1.0


def test_score_is_deterministic_under_filler_shuffles() -> None:
    baseline = summarize_quality(_SOURCE, f"{_SALIENT} shipped")
    rng = random.Random(106)
    filler_words = _FILLER.split()
    rng.shuffle(filler_words)
    shuffled = f"{_SALIENT} {' '.join(filler_words)}"
    assert summarize_quality(shuffled, f"{_SALIENT} shipped") == baseline


def test_score_is_bounded_to_unit_interval() -> None:
    assert 0.0 <= summarize_quality(_SOURCE, _SOURCE) <= 1.0
    assert 0.0 <= summarize_quality("", "anything") <= 1.0
    assert 0.0 <= summarize_quality("a", "aaaa aaaa aaaa") <= 1.0
