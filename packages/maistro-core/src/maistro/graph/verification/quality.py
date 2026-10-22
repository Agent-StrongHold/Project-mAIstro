"""Deterministic self-reported quality for shipped model nodes (epic M4-I).

The escalation gate in :mod:`maistro.graph.verification.escalation` consumes
a quality the *node* reports about its own output — supervision cannot guess
what "good" means for work it never read. But a gate nobody feeds is a gate
that never opens: without at least one shipped node self-reporting, the whole
ladder stays a tested policy with no production input.

:func:`summarize_quality` is that input for ``llm.summarize``. It is
deliberately deterministic and structural — no second model call judging the
first (that would be a billable loop), just the two claims a summary makes
that can be checked against its source for free:

- **compression** — a summary must be shorter than its source (a "summary"
  longer than the source copied it), and not so short it says nothing;
- **coverage** — the source's salient words should survive into the summary.

Both are necessary, neither is sufficient, and the score is a floor, not a
verdict: ``0.5 * compression + 0.5 * coverage``. A graph that wants a
stronger signal declares a higher ``quality_floor``; a graph that finds the
heuristic wrong for its workload does not declare a ladder on the node at
all. The number exists so the cheap-first ladder has something honest to
escalate on, and it never blocks a node whose graph declared no ladder.
"""

from __future__ import annotations

import re

#: Salient tokens: alphanumeric runs of five or more characters, lowercased.
#: Four or fewer excludes most stop words without carrying a stop-word list
#: across every call site.
_SALIENT = re.compile(r"[A-Za-z0-9]{5,}")

#: Compression ratio window that earns full credit: at least 1/32 of the
#: source (a shorter summary says nothing) and at most 75% (a longer one
#: copied the source).
_MIN_RATIO = 1.0 / 32.0
_MAX_RATIO = 0.75
#: The ratio at which compression credit is exactly zero. A summary at least
#: as long as its source copied it and scores no compression credit; between
#: ``_MAX_RATIO`` and here credit falls steeply, so a near-copy does not sail
#: through on coverage alone.
_COPY_RATIO = 1.0


def summarize_quality(source: str, summary: str) -> float:
    """Score one summary against its source in ``[0.0, 1.0]``.

    Deterministic and dependency-free so the same pair always scores the
    same: a quality gate whose input moved between visits would escalate at
    random. An empty summary scores ``0.0`` — the one case no floor should
    pass — and an empty source with a non-empty summary scores on shape
    alone, because there was nothing to cover.
    """
    summary_text = (summary or "").strip()
    if not summary_text:
        return 0.0
    source_text = (source or "").strip()

    compression = _compression_score(source_text, summary_text)
    coverage = _coverage_score(source_text, summary_text)
    quality = 0.5 * compression + 0.5 * coverage
    return round(min(1.0, max(0.0, quality)), 4)


def _compression_score(source: str, summary: str) -> float:
    """Full credit inside the compression window; steep decay to zero at a copy."""
    if not source:
        # Nothing to compress: a non-empty answer to an empty source is not
        # penalized for length (coverage carries the empty case instead).
        return 1.0
    ratio = len(summary) / max(len(source), 1)
    if ratio >= _COPY_RATIO:
        return 0.0
    if ratio < _MIN_RATIO:
        # Too terse: scale up from zero so a one-word summary scores near 0.
        return ratio / _MIN_RATIO
    if ratio <= _MAX_RATIO:
        return 1.0
    # Between the window and a copy: steep linear decay, reaching 0 exactly
    # at ``_COPY_RATIO``.
    return max(0.0, 1.0 - (ratio - _MAX_RATIO) / (_COPY_RATIO - _MAX_RATIO))


def _coverage_score(source: str, summary: str) -> float:
    """Fraction of the source's salient tokens retained in the summary."""
    salient = set(_SALIENT.findall(source.lower()))
    if not salient:
        return 1.0
    summary_lower = summary.lower()
    retained = sum(1 for token in salient if token in summary_lower)
    return retained / len(salient)


__all__ = ["summarize_quality"]
