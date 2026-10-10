---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job 8ba87d85

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`633281a7be01279c9e26c4fc2fab5bb193e52e25` (develop base `4aa68edc0b6b`).
Delta vs the previously verified head `63009d935` is one docs-only commit
(the bb432f91 evidence note), so all functional code is identical; every leg
below was nevertheless re-executed fresh at this head, not inherited.

No production code, ledger, grant, gate or test file was edited this round:
independent verification pass with one added evidence note.

## Driver logs (job 8ba87d85, check-0..4)

`uv sync --locked --extra dev` ok; `ruff check .` "All checks passed!";
`ruff format --check .` 3270 files already formatted; focused `pytest
test_root_admission_identity.py test_admission_codec.py -q -x` → 201 passed,
3 skipped (the 3 skips are the PG legs before a DSN is configured);
`check-suite-inventory.py --suite packages/maistro-core/tests` ok (16401
identities, 0 duplicates, 0 byte-identical files).

## Independent reruns at 633281a

- Focused: `pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q` →
  **201 passed, 3 skipped**; mypy on the two changed production modules →
  no issues in 2 source files. All ten prospective tests named by the issue
  body are present in `test_admission_codec.py`.
- CI `test` job Python legs (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`):
  server+turing+turing/backend+design → **1417 passed, 9 skipped** (50s);
  ext-harness+ext-sdk → **420 passed** (12s); root `tests/
  --ignore=tests/tools/registry` → **4971 passed, 129 skipped** (4m46s);
  hive-conductor backend → **3626 passed, 19 skipped** (2m36s); one-process
  leakage proof `tests/ packages/hive-conductor/backend/tests
  packages/maistro-design/tests -q --timeout=60` → **9262 passed,
  149 skipped** (7m50s). The lane brief's `test: failure` is stale: every
  leg of the named job passes at this head.
- Frontend legs of the same job: hive-conductor `npm run lint` → 0 errors
  (94 warnings), `npm run build` → success; generated-API-types gate
  (`dump-hive-openapi.py` + `gen:api` + `git diff --exit-code`) → **no
  diff**; canvas `npm run test:ci` → **79 passed**, `npm run lint` → 0
  errors (13 warnings), `npm run build` → success.
- Quality gates: `check-reachability.py` exit 0 (1394 modules, 171
  unreachable); `check-reachability-dispositions.py` exit 0 (50 groups
  cover all 171); `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exit 0 (1323 = 1323).

## Exact-debt-ledger residual (unchanged, external)

`RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py` still fails
its inventory with exactly the two known findings
(`maistro.runs.admission_identity`, `maistro.tasks.admission_codec` — NEW
unreachable module / NEW disposition against base `4aa68edc0b6b`;
`check-reachability-provenance.py` alone shows both). Structural cause
re-confirmed in source this round: `scripts/ratchet_provenance.py:478
load_authorizations` reads `quality/ratchet-authorizations.json` **from the
base revision**, so an in-branch grant is inert by construction (the
module's own docstring: "a new grant does not take effect in the change
that introduces it" — the two-merge rule). The issue body forbids
"baseline/grant/gate modifications to make an unwired slice green", and this
lane holds no GitHub write authority, so the resolution stays external:
land the reachability authorizations on the integration base first, then
merge the base into `auto-1893`. Unchanged across 86cf62ae → be3316db →
bb432f91 → this round.

## Durability re-proof on a fresh disposable PostgreSQL 18

New container `b2verify-pg` (`pgvector/pgvector:pg18` = PostgreSQL **18.6**,
127.0.0.1:55991, db `b2probe`), used for nothing else:

1. Destructive-first ordering per the issue: `pytest
   tests/migrations/test_migration_chain.py` on the raw server →
   **18 passed** (59s), chain and downgrade proven before any runtime use.
2. `alembic upgrade head` → real chain 001 → `062_audit_cursor_indexes`
   (head 062).
3. `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…`
   (same DB) over `packages/maistro-core/tests/runs/
   test_root_admission_identity.py` + `tasks/test_admission_codec.py` →
   **204 passed, 0 skipped** (1.67s): the raw-vs-production-pool codec leg
   ran live against the migrated schema for unbound/bound/acknowledged
   states.
4. `pg_get_constraintdef` for `ck_task_idempotency_v2_identity` (migration
   055) read from the live DB contains exactly the clause asserted at
   `test_admission_codec.py:134-137`: `((task_id IS NULL AND run_id IS
   NULL) OR (task_id IS NOT NULL AND run_id IS NOT NULL AND task_id =
   receipt_id))`, plus acknowledged_at ⇒ bound pair.
5. Negative probe on the live DB: a direct SQL INSERT with `task_id =
   'task-mismatch' ≠ receipt_id` and both binding columns set → **rejected
   by the CHECK** (`violates check constraint
   "ck_task_idempotency_v2_identity"`); the storage contract
   `encode_admission_record` writes against is enforced by the schema, not
   only by the codec.
6. Post-run residue: `SELECT count(*) FROM task_idempotency` → **0 rows**.
   Container removed after evidence capture.

## Verdict inputs

- All issue-B2 acceptance criteria re-proven at this head except the
  merge-queue provenance leg, whose failure is the documented external
  two-merge residual above — not reproducible in-branch by any permitted
  action of this lane.
- CI `test: failure` (the named gate failure for this round): not
  reproducible; all legs re-run fresh and green at 633281a.
