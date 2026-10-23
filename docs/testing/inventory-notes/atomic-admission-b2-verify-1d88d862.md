# Verification round at 6af21c54e — #1893 B2 admission codec (job 1d88d862)

inventory-delta:
  suite: packages/maistro-core/tests
  baseline: 16567
  after: 16567
  delta: 0
  reason: "no test files added, removed, or renamed this round; docs-only verification note"

## Scope of the round

Fresh verification of the `auto-1893` head `6af21c54e95f0fca58ae4ac83abee4ed886c025f`
(job `1d88d86253424ab89b17a06e31ce374c`, repair phase). The prior recorded PG
proof head was `66c43a051dc8d093c6dfcc468007d408938b92bd`; this round first
established `git diff 66c43a05..HEAD -- packages/` is empty (only this note
family and `quality/ratchet-authorizations.json` changed since), then re-proved
the durable legs live anyway. No source file was modified this round.

## Driver checks at this head (fresh, this job)

- `uv sync --locked --extra dev` exit 0; `uv run ruff check .` exit 0;
  `uv run ruff format --check .` exit 0 (3301 files).
- Driver focused pytest (4 files, pure mode): 346 passed, 3 skipped.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  exit 0 (16567 identities).

## Focused B2 evidence (fresh runs)

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
  → 201 passed, 3 skipped (skips are the PG-leg contrast tests without a DSN).
- `uv run mypy packages/maistro-core/src` → Success, no issues in 791 files.
- All 10 prospective tests named in the issue body are present
  (`test_v2_round_trip_preserves_all_snapshot_bytes` …
  `test_raw_and_production_pool_codecs_read_identical_text_snapshots`).
- Prior repairs confirmed in place: `encode_admission_record` emits
  `task_id`+`run_id` together from the binding
  (packages/maistro-core/src/maistro/tasks/admission_codec.py:291-292);
  `AdmissionRecordV2` rejects `binding.receipt_id != envelope.receipt_id`
  (packages/maistro-core/src/maistro/runs/admission_identity.py:291-292);
  `test_v2_round_trip_preserves_all_snapshot_bytes` asserts the migration-055
  CHECK shape independently of encode/decode agreement
  (packages/maistro-core/tests/tasks/test_admission_codec.py:134-137).

## CI `test` job disproven again at this head (CI-exact args/env)

- `tests/ --ignore=tests/tools/registry -q` → 4982 passed, 135 skipped.
- `packages/maistro-server/tests` → 557 passed, 8 skipped.
- `packages/maistro-turing/tests` → 210 passed;
  `packages/maistro-turing/backend/tests` → 90 passed.
- `packages/maistro-design/tests` → 572 passed, 1 skipped.
- `packages/maistro-ext-harness/tests` → 273 passed;
  `packages/maistro-ext-sdk/tests` → 147 passed.
- Cross-suite single-process leg
  (`tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests
  -q --timeout=60`) → 9273 passed, 155 skipped.
- `python scripts/check-suite-inventory.py` (full) → ok, 17 suites;
  `python scripts/check-test-duplicates.py` → ok.
- `scripts/dump-hive-openapi.py` exit 0 and
  `packages/hive-conductor/frontend/src/api/types.gen.ts` unchanged (the
  branch's production footprint is maistro-core only, so the OpenAPI document
  cannot move). Frontend trees are untouched by the branch diff.

## exact-debt-ledger steps at this head

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1322 reviewed
  identities = 1322 findings: no unbanked identity, so the permitted CI-repair
  amendment of `quality/vulture-baseline.json` has no target; untouched.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
- `uv run python scripts/check-reachability.py` → exit 0 (171 unreachable of
  1403, all dispositioned); `scripts/check-reachability-dispositions.py` →
  exit 0 (50 groups).
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
  → exit 1 on exactly `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` ("NEW ... not previously authorized"); every
  other ratchet in the same run is OK, including promotion-surface.

## Real-database durability re-proven at this head

Disposable `pgvector/pgvector:pg18` (PostgreSQL 18.6) container, fresh database
`b2r1893_1d88d`:

- `DATABASE_URL=... uv run alembic upgrade head` → chain 001→063, exit 0.
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=...
  uv run pytest <codec><identity><cli_lock><pack_contracts> -q` →
  **349 passed, 0 skipped** (no fake/skipped PG counted).
- Live storage-contract probe on the migrated chain:
  `ck_task_idempotency_v2_identity` present; a valid format-2 row produced by
  `encode_admission_record` INSERTs (task_id = receipt_id satisfied the CHECK);
  the identical row with `task_id <> receipt_id` is rejected by
  `ck_task_idempotency_v2_identity`; the inserted row decodes back through
  `decode_admission_header`/`decode_admission_record` into an `AdmissionRecordV2`
  equal to the original. Table truncated afterwards (`count(*) = 0`); the
  disposable database was dropped.

## Two-merge wall (unchanged, structural, develop-side)

`git fetch origin` this round: `origin/develop` is still `ab8b3737` — the
reachability grant has not landed there. The branch-side grant
(`quality/ratchet-authorizations.json`, commit `6af21c54e`) is byte-identical in
its #1893 rows to probe commit `3235229f5fed`, whose probe merge previously
proved the provenance gate passes once the grant is the trusted base. Per the
two-merge rule, `check-ratchet-provenance.py` reads authorizations from the
merge base, so a candidate-side grant can never authorize its own introduction:
the remaining red is resolved only by the owner landing this grant on develop
and develop being merged into `auto-1893` — a develop-side action outside
worker authority (no pushes/mutations permitted). Issue #1893's
"no baseline/grant/gate modifications to make an unwired slice green" is not
violated by the staged grant: it cannot green anything from the candidate side.

## Handoff state

All engineering acceptance criteria of the B2 leaf are proven at this head with
fresh execution. The only red required job (`exact-debt-ledger`'s provenance
step) is the documented structural wall above; the named `test: failure` is
disproven with the full CI leg set above. Required next action (owner):
land the reachability grant on `develop`, then merge `origin/develop` into
`auto-1893` and re-run `RATCHET_BASE_REV=origin/develop uv run python
scripts/check-ratchet-provenance.py`.
