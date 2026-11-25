# RSI backoff-ladder boundary slop (#2303 CI repair)

No suite-count delta: no test was added, removed, renamed or skipped; one
test's timing-boundary slop was widened. No `inventory-delta` block is
recorded because no count moved.

## What changed and why

`packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts::a prolonged
outage backs off exponentially: exact doubling gaps bounded at the 60s cap`
failed twice (initial attempt + retry #1) on the #2303 merge-queue evaluation
(CI job 133112496460 at 58cc1eb), reding `hive-conductor-e2e-ui` and, through
it, `integration-scope`. Both failures are boundary-slop misses, not cadence
regressions:

- Attempt 1: `stamps[n0+1] − flipEnd − 7_500` measured **1000** against the
  10ms budget at the "first backoff step" assertion.
- Retry #1: a capped gap measured **45015** against the 45010ms budget
  ("the cap floors the cadence at ~45s").

The bound anchors two different clocks: `flipEnd` is REAL time
(`Date.now()` captured before `clock.runFor(10_000)`) while the stamps are
VIRTUAL time, and outside `runFor` chunks the fake clock ticks 1:1 with real
time — so every real millisecond the settles and poll nudges actually take
leaks into the assertion. The original 10ms slop only budgeted the documented
5ms safety nudge; a loaded CI runner's settle drift was observed at ~1s.

The fix widens the boundary slop to a named 2.5s `BOUNDARY_SLOP` used at all
four sites (first backoff step, both doubling checks, both cap checks).
Everything the test exists to prove still fails hard on a real regression:
a fixed 5s cadence misses `near(gaps[0], 15_000)` by 10s, unbounded growth
misses the cap check by ~45s, and the 5-minute burn-count bound (≤8 polls)
is untouched.

## Evidence

- Same test, same digest, standalone on the rebuilt harness image: failed at
  first attempt locally too (received 45020 vs 45010 — third instance of the
  same boundary noise; jobs jobs 133112496460 ×2 and one local run), passed
  twice standalone before the change, passed once after the change.
- The spec is byte-identical to develop (no branch-introduced change); the
  flake is trunk-inherited brittleness exposed under runner load, and
  develop's own 2026-11-08 run at f8a2df966 passed the suite.
- Full local compose run at 58cc1eb (before this edit): exit 0, 245 passed,
  1 flaky (a different spec retried clean) — the suite itself is healthy.
