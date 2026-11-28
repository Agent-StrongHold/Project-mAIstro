# 2538-lane — task-stream heartbeat bound re-calibrated; hosted `test` flake repaired

Lane L2538 (issue #2538, branch `auto-2538-2538-investigate-two-gitleaks-findings-on`).
The gitleaks repair itself adds no tests (see
`REPAIR-NOTES-2538-gitleaks-squash-drift.md` for why none is possible); this
round additionally repairs the one red hosted gate on the lane head.

inventory-delta:
  packages/hive-conductor/backend/tests: +0

## What changed

`packages/hive-conductor/backend/tests/test_task_stream_event_loop.py`
`test_stalled_ownership_probe_does_not_block_the_loop`: the heartbeat
assertion bound moved from `max_gap < 0.25` to `max_gap < 1.0`, with an inline
comment recording the calibration evidence. No test added, removed, renamed,
or re-parameterized — node IDs for the suite are unchanged, which is why the
delta is +0 and `scripts/check-suite-inventory.py` still reports 21/21 suites
matching.

## Evidence the hosted failure is noise, not a regression

- Hosted `test` job at lane head `e5d1f50d95` (run 46136926512, job
  140954186898) failed exactly one test:
  `AssertionError: event loop stalled for 0.38s` against a 0.25s bound.
- The lane's entire diff at that head is three non-Python files
  (`.gitleaksignore`, `CHANGELOG.md`, `REPAIR-NOTES-*.md`) — `git diff
  origin/develop --stat` shows nothing under `packages/`. The test file's own
  history is untouched since #1717.
- Local replication at the same head: the failing test passed 5/5 in
  isolation and the full backend suite passed
  (`uv run python -m pytest packages/hive-conductor/backend/tests -q` →
  **4655 passed, 121 skipped** in 4:27), twice (before and after the bound
  change).
- A 0.38s heartbeat gap on a loop whose stall detector targets a 2.0s
  blocking probe is CFS throttling / GC pause on a shared runner, not a
  blocked loop; the bound of 0.25s sat inside the runner's noise floor, so
  the assertion could fail with no regression present.

## Why a bound change is the repair, not a gate weakening

Repo doctrine warns against "a bound that encodes the current machine's
speed". A threshold below the measured noise floor makes the detector lie in
both directions on loaded runners. 1.0s repositions it between the observed
noise floor (0.38s hosted) and the stall under test (2.0s), preserving a 2x
detection margin.

## Red-check (both directions)

A scratch test (written, executed, deleted — not committed) replicated the
heartbeat pattern:

- loop genuinely pinned via on-loop `time.sleep(2.0)`: registered
  `max_gap >= 1.9s` — the shipped assertion fails hard against the regression
  it names;
- probe waiting off-loop (`await asyncio.sleep(2.0)`): `max_gap < 1.0s` —
  the shipped assertion passes, as the production behavior requires.

## Post-change validation

- Target test 5/5 pass; whole file 5 passed.
- Full backend suite at the changed head: 4655 passed, 121 skipped.
- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- `scripts/check-suite-inventory.py`: 21/21 suites match (+0 delta).
- `scripts/check-test-duplicates.py`: 0 byte-identical groups.
