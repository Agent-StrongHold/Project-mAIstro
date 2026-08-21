"""Improvement taxonomy — the kinds of change the RSI scout can propose, and
what each kind means for *budget* and *scoring* (ADR-070126-6386 v2).

The scout tags every shortlist item with an ``ImprovementKind``. That one flag
is the routing key for everything downstream:

- **Budget** — how much compute a competitor may spend on it. Correctness and
  verification work is a bounded, single-file (+ its test) change; a ``FEATURE``
  ("v2.0") is ambitious multi-file work that unlocks a large token/turn budget.
- **Scoring** — which fitness signals decide promotion. Correctness is cheap to
  score objectively (tests pass, coverage rises, red→green); a feature is not, so
  it is judged by the LLM impact judge plus a capability/benchmark delta when one
  exists (see ``candidate_fitness``/``scorecard``).

The point of the loop is recursive self-improvement — real growth up to a module
"v2.0" — not docstring churn, so ``DOC`` is a last-resort fallback only.
"""

from __future__ import annotations

from enum import StrEnum


class BudgetTier(StrEnum):
    """How much a single competitor may spend on one item."""

    BOUNDED = "bounded"  # one focused change to the target file (+ its test)
    UNLOCKED = "unlocked"  # ambitious: multi-file, many turns, high token budget


class ImprovementKind(StrEnum):
    """The kind of improvement a scout item proposes.

    Ordered by the scout's default *preference* when several are available on a
    module (see :pyattr:`priority`): correctness and verification before growth,
    with ``DOC`` only when nothing better is warranted.
    """

    BUG_FIX = "bug_fix"  # code violates its contract — turn red→green
    NEW_TEST = "new_test"  # evidence-based test for untested behavior
    ASSERTION = "assertion"  # strengthen a test that asserts too little
    SPEC = (
        "spec"  # implement a specific UNIMPLEMENTED acceptance criterion (finish contracted work)
    )
    BACKLOG = "backlog"  # draft a NEW spec for a genuinely good idea — the disciplined alternative to hacking in an unspecced feature
    FEATURE = "feature"  # a genuinely better capability/API/design (v2.0)
    EDGE_CASE = "edge_case"  # a boundary/error path with no test
    REFACTOR = "refactor"  # behavior-preserving clarity/DRY/complexity win
    PERF = "perf"  # a measurable performance optimization
    DOC = "doc"  # docstring/type — fallback only, never the goal

    @property
    def budget(self) -> BudgetTier:
        """SPEC/BACKLOG/FEATURE are the tiers that unlock the large, multi-file
        budget — each is inherently multi-file (implementing an AC across code
        + tests, drafting a new spec doc, or building a v2.0 capability)."""
        return (
            BudgetTier.UNLOCKED
            if self in (ImprovementKind.SPEC, ImprovementKind.BACKLOG, ImprovementKind.FEATURE)
            else BudgetTier.BOUNDED
        )

    @property
    def priority(self) -> int:
        """Scout preference rank (lower wins) when several kinds are available."""
        return _PRIORITY[self]

    @property
    def primary_signals(self) -> tuple[str, ...]:
        """The fitness signals that chiefly reward this kind (for docs/routing).

        Names match the ``SignalScore``/gate names produced by ``candidate_fitness``.
        A kind is not *limited* to these — every candidate is scored by the whole
        Scorecard — but these are the ones its acceptance hinges on.
        """
        return _PRIMARY_SIGNALS[self]

    @classmethod
    def from_str(cls, value: str) -> ImprovementKind:
        """Parse a scout-emitted kind leniently; unknown/blank → ``DOC`` (safe fallback)."""
        try:
            return cls(value.strip().lower())
        except (ValueError, AttributeError):
            return cls.DOC


# Preference order — the maturity ladder: correctness (bug→test→assertion) →
# finish CONTRACTED work (spec) → propose disciplined NEW work (backlog: draft a
# spec instead of hacking in a feature raw) → growth (feature) → edge → refactor
# → perf → doc-fallback. Finishing a promise you already made outranks either
# inventing one (backlog) or shipping one un-specced (feature); proposing a new
# spec still outranks shipping a raw feature — it's the disciplined path from
# idea to contracted, testable work. Tunable; the scout may still rank by impact.
_PRIORITY: dict[ImprovementKind, int] = {
    ImprovementKind.BUG_FIX: 0,
    ImprovementKind.NEW_TEST: 1,
    ImprovementKind.ASSERTION: 2,
    ImprovementKind.SPEC: 3,
    ImprovementKind.BACKLOG: 4,
    ImprovementKind.FEATURE: 5,
    ImprovementKind.EDGE_CASE: 6,
    ImprovementKind.REFACTOR: 7,
    ImprovementKind.PERF: 8,
    ImprovementKind.DOC: 9,
}

_PRIMARY_SIGNALS: dict[ImprovementKind, tuple[str, ...]] = {
    ImprovementKind.BUG_FIX: ("red_green",),
    ImprovementKind.NEW_TEST: ("new_test", "coverage"),
    ImprovementKind.ASSERTION: ("assertion_strength",),
    ImprovementKind.SPEC: ("spec_completion", "new_test"),
    ImprovementKind.BACKLOG: ("spec_proposed", "code_quality"),
    ImprovementKind.FEATURE: ("feature_judge", "capability"),
    ImprovementKind.EDGE_CASE: ("new_test", "coverage"),
    ImprovementKind.REFACTOR: ("code_quality",),
    ImprovementKind.PERF: ("perf", "capability"),
    ImprovementKind.DOC: ("code_quality",),
}
