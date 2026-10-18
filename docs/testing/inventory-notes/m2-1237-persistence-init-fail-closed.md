---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# m2-1237 — persistence initialization must fail closed

Issue #1237 replaces the Foundation state fallback with a startup failure and
removes the lifespan fallback that rebound security-critical stores to memory.

- `packages/hive-conductor/backend/tests/test_foundation.py` (+2): the new
  lifespan regression proves a Foundation state failure propagates and never
  calls `stores.initialize_stores()`. The strengthened state-failure test proves
  the boundary does not publish an empty user registry and that cleanup
  failures are logged while the original persistence error remains the startup
  failure; a constructor-failure case covers the no-state cleanup branch.

## Verification record (independent, head 13d50ca6)

- Re-ran `uv run pytest packages/hive-conductor/backend/tests/test_foundation.py -q`:
  19 passed. Re-ran the full backend suite: 2257 passed, 11 skipped (2268 =
  recorded inventory). `uv run ruff check .`: clean.
  `scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`: ok.
- Regression proof: on base 78bb7290 the `_init_state` except-branch swallowed
  the failure and called `stores.initialize_stores()`, so the new
  `pytest.raises(RuntimeError, match="STATE_UNAVAILABLE...")` and
  `initialize_calls == []` assertions could not pass; the lifespan regression
  likewise fails on the old caught-then-rebind path in `main.py`.
- Residual-fallback sweep: `initialize_stores` has no production caller outside
  the `_init_state` success path; `EphemeralSettingsRecordStore` remains only as
  the pre-foundation default, unreachable once startup fails closed.
- No premature closure keywords in branch commits 450dd91d..13d50ca6.

## Verification record (independent re-run, head 2f9569eb)

Second independent verification after the develop merge (551c38b5) landed in
aud1. All commands executed on exact head 2f9569eb55b8dd927c01945a810e5229be5414ca,
worktree clean before and after:

- `uv run pytest packages/hive-conductor/backend/tests/test_foundation.py -q`:
  19 passed. Full backend suite: 2257 passed, 11 skipped, 0 failed.
  `uv run ruff check .`: clean; `uv run ruff format --check .`: clean (2420
  files). `scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: ok at 2268.
- Regression proof repeated against the actual merge base: base tree extracted
  with `git archive 551c38b5` into a scratch dir and the head test file
  overlaid. Result: exactly the 3 new regression tests fail, each with
  `DID NOT RAISE <class 'RuntimeError'>` (the silent in-memory fallback this
  issue closes); the other 16 pass, so the failures are surgical to the fixed
  behavior.
- Fail-closed chain re-read at head: `Foundation.start` calls `_init_state`
  unguarded; `start_foundation` does not catch; `main.py` lifespan no longer
  catches — RuntimeError aborts startup. `initialize_stores` has no production
  caller outside the `_init_state` success path.
- Closure-keyword scan of `551c38b5..2f9569eb` commit subjects/bodies: none
  found.
