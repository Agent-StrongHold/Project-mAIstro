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

## Repair-round exact-head revalidation at `227eb15590f2`

The assigned job directory contained no `check-*.log` files, so there were no
verifier check logs to inspect. The prior result's single finding is the
integration-only negative-before/positive-after CI closure gate; this local
worktree cannot trigger that post-integration evidence. I independently
revalidated reachable production behavior and reviewed accepted ADR-082126-f69c
(which supersedes ADR-046) and ADR-082426-82c7. The scheduler/store/test
implementation paths are byte-identical to `fce56cf3fe`, whose committed
validation records real-PG and projection-restart execution.

Fresh commands at this exact head:

- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py packages/maistro-core/tests/scheduling/test_store.py packages/maistro-core/tests/scheduling/test_admission_backend_parity.py tests/cross_product_parity/test_cross_product_parity.py -k 'schedule or scheduler' -x -q` — **62 passed, 39 skipped, 105 deselected**; PostgreSQL-specific skips are not claimed as fresh evidence.
- Strict closeout: `MAISTRO_PARITY_MODE=m1-closeout MAISTRO_PARITY_STRICT=1 uv run pytest tests/cross_product_parity/test_cross_product_parity.py -k 'schedule_required or schedule_fire or scaffold_only' -x -q -s` — **3 passed**; emitted `executed=true`, `status=PASSED` for `scheduler-occurrence-to-conductor`.
- `uv run ruff check . && uv run ruff format --check .` — passed (3644 files).
- CI-exact vulture baseline — passed; 1221 reviewed identities equal 1221 findings.

Source review confirms `_ScheduleRunner._tick_due` iterates
`container.schedule_store.due(now=now)`, rereads the canonical definition
under `definition_lock`, and refuses deleted/disabled or no-longer-due rows;
the canonical store persists cursor state. This does not replace prior
first-party PostgreSQL evidence with a fresh PG run. All behavioral criteria
are covered by current tests and prior committed exact implementation
validation; the explicit integrated-CI negative-before/positive-after clause
remains **UNVERIFIED**, so this is a validation handoff, not integration
approval. No tests were added or removed; inventory delta remains zero.

## Repair-round exact-head revalidation at `627c83e9fb`

No `check-*.log` files were present in the assigned job directory. Re-ran the
focused scheduler/store/parity selection at the assigned head:

- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py packages/maistro-core/tests/scheduling/test_store.py packages/maistro-core/tests/scheduling/test_admission_backend_parity.py tests/cross_product_parity/test_cross_product_parity.py -k 'schedule or scheduler' -x -q` — **62 passed, 39 skipped, 105 deselected**.
- Strict M1 closeout command — **3 passed**, with `scheduler-occurrence-to-conductor` emitted as `executed=true`, `status=PASSED`.
- Source grep confirms the live tick enumerates `container.schedule_store.due()` at `services/scheduler.py:783`; other `stores.schedules` uses are projection, reconciliation, or compatibility paths, not tick candidate authority.

No test functions were added or removed. Fresh PG and post-integration
negative-before/positive-after CI evidence remain unverified in this round; the
committed real-PG evidence remains cited in the preceding exact-head notes.
