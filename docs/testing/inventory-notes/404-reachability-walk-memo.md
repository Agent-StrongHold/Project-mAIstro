---
inventory-delta:
  tests/: +0
---

# Coverage-gate repair: memoize the reachability walk inside its own test module

The merge-queue evaluation of auto-404 at `b837ac5ebbd5` failed the
**Coverage gate (publish-set floor + diff coverage)** — but not on any
coverage number. The `combine` step's root producer
(`coverage run --branch --source=scripts -m pytest tests/ ... --timeout=30`)
died on two pytest-timeout failures before `coverage xml` and the diff gate
ever ran (run `37879373619`, job `113657357275`):

```
FAILED tests/test_check_reachability.py::test_new_unreachable_module_fails_the_gate - Timeout (>30.0s)
FAILED tests/test_check_reachability.py::test_module_becoming_reachable_fails_until_the_baseline_is_pruned - Timeout (>30.0s)
2 failed, 5005 passed, 128 skipped
```

The same hour, the same two timeouts failed the identical job on auto-978
(run `37876585845`) and auto-1852 (run `37876462146`) — branches whose diffs
touch none of this — while earlier the same day the full gate passed on this
branch's own #404 content at head `47ba4898` (run `37876106645`, all jobs
green; `git diff 47ba4898..b837ac5 -- packages/maistro-core/src/maistro/tools/git/server.py`
is empty). So the failure is a latency boundary in shared test
infrastructure, not the #404 change.

## Cause

`tests/test_check_reachability.py` loads the gate script once (module-scoped
`check` fixture), but every public entry point re-walks the whole repository:
`unreachable_modules()` and `main()` each call `_reachability` from scratch.
The two ratchet-direction tests call both, doubling the cost. Measured:
7.3s/test without tracing, 18.4s/test under the producer's `--source=scripts`
tracing — and past the workflow's 30s per-test ceiling on slower runners.

## Repair

A module-scoped autouse fixture (`_walk_once_per_distinct_arguments`) wraps
`check._reachability` with a memo keyed on the call arguments and returns a
copy of the mutable dict/set. The graph is a pure function of the tree, and
this file deliberately keeps the tree static — baseline changes are
simulated by monkeypatching `BASELINE`, never by writing into `packages/` —
so identical arguments have identical results within a session. No test
assertion changes; no production code changes (other consumers load the
script into their own module objects via their own `spec_from_file_location`
calls and are untouched). Restored afterwards at module teardown.

Node count is unchanged: the file still collects 24 tests, the root suite
still 5007 passed + 128 skipped, matching the CI run at this head
(2 + 5005 + 128). Hence the `+0` delta; `check-suite-inventory.py` needs no
baseline move.

## Evidence (all commands at head b837ac5 + this fix)

- `uv run pytest tests/test_check_reachability.py -q --timeout=30`
  → 24 passed in 4.28s (was 37.45s).
- Exact failing producer command, under tracing:
  `uv run coverage run --branch --source=scripts -m pytest tests/
  tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30 -q`
  → **5007 passed, 128 skipped, 0 failed** in 626s (CI failed this exact
  command; the two named tests pass with ~10s first-walk cost and ~0s
  thereafter).
- Diff-coverage pillar, with real combined data (scripts + maistro-core
  producers appended) and the develop base:
  `uv run coverage xml -o /tmp/coverage-404.xml` then
  `uv run python scripts/check-diff-coverage.py /tmp/coverage-404.xml
  --base 675db8be6c41b020ffffb224b2748c159c78a122`
  → `ok: every measured file this change touches is at or above 90% lines /
  80% branch arcs` (exit 0; 1 measured file = the #404 `server.py`, 4 exempt
  test files).
- Publish-set floor: untouched by this fix (test-only change, zero source
  statements); it already passed inside the failed CI run — the combine step
  runs `coverage report --fail-under=87` before the root producer, and the
  run reached the root suite's pytest summary.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.

## Known-environmental, not introduced here

Locally (not in CI) the maistro-core producer shows 2 pre-existing failures
in develop-inherited files this branch never touched —
`test_certify_refuses_a_malformed_signing_key` and
`test_compat_preflight_rejects_unreadable_input` assert bare substrings
(`"not a hex Ed25519 private key"`, `"not valid JSON"`) while the local
environment wraps the CLI error after `"is not"`. The branch's diff does not
include those tests, their modules, or `uv.lock`, so the behavior is
identical at base and head; CI's `coverage (no services)` job passed at this
exact head. They are recorded here so the next reader does not mistake them
for lane regressions.

## Correction (repair round)

The front-matter delta key above was first written as `tests: +0` — without
the trailing slash — so the ledger recorded a suite named `tests` that no
`RECIPES` entry collects, and every `check-suite-inventory.py` invocation
failed closed before comparing any count:

```
error: recorded suites with no collection recipe in check-suite-inventory.py: tests
       Add each to RECIPES so it is actually gated.
```

The suite being described is the root `tests/` suite (the memoized module is
`tests/test_check_reachability.py`), whose recipe and baseline key are spelled
`tests/` — the same spelling the earlier
`858-turing-provision-reachability-root` note uses. The key is corrected to
`tests/: +0`; the count itself was and remains `+0` (memoization changes no
collected node IDs).

### Evidence at the repair head (ff51e5bcb, gate re-proven)

Re-executed at the head carrying this correction, with CI's exact argv:

- `python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  → exit 0 (16038 node IDs, 0 duplicates); the full 17-suite run → exit 0
  (30592 identities, root `tests/` at 5124).
- The coverage gate's root producer — the exact command CI timed out on at
  b837ac5 (`coverage run --branch --source=scripts -m pytest tests/
  tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  --timeout=30 -q`) → **5006 passed, 129 skipped** in 627s; the two
  `test_check_reachability.py` ratchet tests that died at >30s now pass inside
  the ceiling (file alone: 24 passed in 4.5s).
- Diff pillar with real combined data (core git-suite producer under
  `--source=packages/maistro-core/src/maistro` + the root producer above):
  `check-diff-coverage.py coverage.xml --base c4bd944393` → exit 0, 1 measured
  file (`tools/git/server.py`), 5 exempt test files.
- `ruff check .` / `ruff format --check .` clean; lane set
  (`test_server_security.py` + RSI `test_cli.py`/`test_harvest_entry_point.py`/
  `test_selfbranch.py`) → 138 passed; vulture exact-debt ledger
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) exit 0
  (1323 = 1323, baseline read from the declared base c4bd944393) — no ledger
  amendment needed this round.
- Environmental, not the branch: the root producer's one local failure before
  this correction round's cleanup was
  `test_every_quality_json_state_surface_is_classified_once` refusing a stray
  **gitignored** `quality/ac-state.json` — a generated artifact
  (`generated_by: scripts/check-ac-state.py`, Oct 8 21:52) left in this
  worktree by an earlier round's ac-state measurement. Fresh CI checkouts do
  not contain the file; moved to `/tmp/maistro-404-salvage/` (preserved, not
  deleted) the test passes and the producer is green as recorded above.
- The publish-set floor pillar (`coverage report --fail-under=87`) is not
  re-measured locally this round (it needs every publish-set producer); in the
  merge-queue run this repair answers (37879373619) that pillar already passed
  before the root producer's timeouts killed the step, and no publish-set
  source file has changed since (`git diff --name-only c4bd944393..HEAD
  -- '*.py'` excludes exactly one non-test source, `server.py`, unchanged
  across every round since the last fully-green hosted run).
