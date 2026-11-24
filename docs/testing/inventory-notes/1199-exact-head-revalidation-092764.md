---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
---

# #1199 exact-head revalidation at 0927640684

The assigned job directory did not contain any `check-*.log` files, so those
were unavailable for inspection. The prior result was not accepted without
fresh validation. The implementation tree is unchanged from `b061209c2f`; the
head-only change through `0927640684` is documentation.

## Fresh validation on this head

- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py packages/maistro-core/tests/scheduling/test_store.py packages/maistro-core/tests/scheduling/test_admission_backend_parity.py -x -q` initially failed because the guessed test path `packages/maistro-core/tests/test_scheduling_store.py` does not exist; corrected selection → **93 passed, 51 skipped**. The skipped cases require PostgreSQL, which was not configured in this shell (`MAISTRO_TEST_PG_DSN` unset).
- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py packages/hive-conductor/backend/tests/test_schedule_canonical_definitions.py -x -q` → **59 passed, 13 skipped** (PostgreSQL legs unavailable in this shell).
- `uv run ruff check .` and `uv run ruff format --check .` → passed (3644 files formatted).
- Exact CI vulture command → **1221 reviewed identities = 1221 findings**, no unbanked identities.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` → passed, 4511 tests match inventory.

## Acceptance cross-check

Production `_ScheduleRunner._tick_due` selects from `container.schedule_store.due(now=...)`, re-reads under `definition_lock`, and the canonical evaluation records no-fire due-cursor advancement. SQLite `record_fire` serializes the cursor read/write; the corresponding store/concurrency and backend-parity coverage is in the selected core suite. Projection startup, tombstone and restart behavior is covered by `test_scheduler_projection_authority.py`. The configured scheduler-to-Conductor closeout and all real PostgreSQL legs were independently recorded at the preceding code-identical head in `issue-1199-projection-authority.md` (445 passed, 1 skipped; strict closeout passed). This round did not re-execute PostgreSQL or strict closeout, so those results are cited as prior committed evidence, not fresh execution.

No test functions were added or removed; the inventory delta is zero.
