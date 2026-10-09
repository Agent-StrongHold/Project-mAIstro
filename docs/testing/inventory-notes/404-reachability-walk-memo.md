---
inventory-delta:
  tests: +0
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
