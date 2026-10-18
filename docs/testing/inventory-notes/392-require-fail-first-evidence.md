---
inventory-delta:
  packages/maistro-rsi/tests: +43
---
# 392-require-fail-first-evidence

## What moved

Repair round (coverage-gate evidence): the refactor alternative contract is now
exercised where it is wired, not only as a pure gate — `test_fail_first.py`
gains three tests (+3): the `evaluate_candidate` refactor wiring judged by the
measured quality delta (improvement accepted + recorded, non-improvement and
unverifiable-baseline rejected), and `_mean_quality_at_base` against a REAL
git repo (baseline scoring; new-module skip with fail-closed None).
`test_local_loop.py` gains two (+2): a full-loop promotion whose git-notes
record carries the real red→green probe (base/candidate SHA, failing
identities, digest, passing result) and the legacy-scorecard tolerance (no
fail_first gate → key simply omitted).

`packages/maistro-rsi/tests/test_fail_first.py` is new (+40 node IDs): nine
parametrized contract-resolution cases plus the promotion gate's rejection
matrix (missing / already-passing / non-reproducible / config-tainted /
unrelated fail-first evidence), the alternative evidence contracts (refactor
quality delta, characterization, documentation), probe parsing and static
relatedness, five REAL git+pytest probe runs (the full red→green proof with
recorded SHAs and digest, a new module written test-first, a candidate
deletion that must not be resurrected, a monkeypatched flaky second probe,
and the config-taint case against a live repo), and the git-notes trace
round-trip.

`test_fixer_tiers.py` gains one test (+1, unchanged this round): the
REFACTOR/DOC fixer scaffold now
demands behavior-preserving polish with a measurable code-quality improvement
instead of the test-first scaffold, and the bounded tiers' scaffold must state
the enforced fail-first proof.

One test in `test_local_loop.py` was adapted in place (no count change): its
candidate now commits before scoring and carries a red-on-base test, because a
source-only candidate with no failing-first test is rejected before the judge
gate can ever run — which is the point of #392.

## Why

Issue #392: a characterization test that snapshots current behavior could be
committed as "test-first" evidence without demonstrating a defect, and nothing
recorded *proof* that a changed test ever failed. The new
`maistro_rsi/fail_first.py` contract classifies every candidate
(behavior / refactor / characterization / documentation), and the promotion
gate rejects missing, non-reproducible, already-passing, unrelated, or
config-tainted fail-first evidence. The evidence itself — base SHA, failing
test identities, failure-output digest, candidate SHA, passing result — rides
the promotion's git-notes record (`TraceNote.fail_first`), so the tests pin
both the enforcement and the audit trail.
