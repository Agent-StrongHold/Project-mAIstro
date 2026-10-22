# #1802 — bound enumeration by work, not wall-clock seconds

`test_a_seven_day_backlog_evaluates_in_bounded_wall_time` was a stopwatch guard
(`assert elapsed < 0.5` via `time.monotonic()`) whose 0.5s bound sat only ~22%
below the ~0.64s pathological value it was written against, so `coverage
run --branch` on a shared runner cleared it with no algorithmic change — exactly
the flake reported in the issue. It also measured the wrong thing: a fast host
passes a latency bound even when enumeration examined far more occurrences than
it should, so the clock could never be a correctness gate.

The test is renamed to `test_a_thirty_day_backlog_enumerates_only_its_catchup_window`
and asserts the invariant directly on the deterministic work performed, with the
time budget disabled so the number is a fact about the window on any host:

- `len(result.fires) + len(result.skipped) == 10080` — one occurrence per minute
  over the seven-day catchup window; the thirty-day cursor is what the walk
  refuses, not a function of the machine.
- `len(result.fires) <= DEFAULT_ENUMERATION_LIMITS.max_enumerated_fires` (512) —
  the fire-list cap, independent of the window.
- `result.enumeration_incomplete == (result.enumeration_stopped_at is not None)` —
  the completed/truncated invariant holds in both directions.
- `result.enumeration_incomplete is False` for the windowed backlog.

`EnumerationLimits(walk_budget_seconds=math.inf)` is passed so `evaluate` stops
on the step/window bound and reaches `now` deterministically; the time-budget
stop path is covered separately by `test_an_expired_budget_marks_the_walk_incomplete_at_where_it_stopped`,
`test_a_step_bound_tighter_than_the_window_marks_the_walk_incomplete`, and
`test_a_zero_budget_stops_before_examining_anything`. `import time` and
`time.monotonic` are gone from the file entirely.

## Inventory

Count-neutral: one test renamed to one test. The scheduling suite lives under
`packages/maistro-core/tests` (recorded 13264 node IDs); collection still matches
the recorded inventory with no delta recorded here, per the convention that a
note is only required to move a count.

## Verification (this worktree, head 31d891a)

- `test_enumeration_limits.py`: 13 passed (plain); 13 passed x10 under
  `coverage run --branch` — the original flake environment — with no failure.
- Full `packages/maistro-core/tests/scheduling/`: 272 passed, 36 skipped.
- `ruff check` / `ruff format --check`: clean for the file.
- `scripts/check-suite-inventory.py`: 14 suites match the recorded inventory.
