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
