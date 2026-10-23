---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job 53aa38a0

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`e43603c901a6cd38606fb32005595c46b6954237` (develop base `4aa68edc0b6b`).
Delta vs the previously verified head `633281a7b` is exactly one docs-only
commit (the 633281a evidence note), so all functional code is identical to
the last fully verified head; every leg below was nevertheless re-executed
fresh at this head, not inherited.

No production code, ledger, grant, gate or test file was edited this round:
independent verification pass with one added evidence note.

## Driver logs (job 53aa38a0, check-0..4)

`uv sync --locked --extra dev` ok; `ruff check .` "All checks passed!";
`ruff format --check .` 3270 files already formatted; focused `pytest
test_root_admission_identity.py test_admission_codec.py -q -x` → 201 passed,
3 skipped (the 3 skips are the PG legs before a DSN is configured);
`check-suite-inventory.py --suite packages/maistro-core/tests` ok (16401
identities, 0 duplicates, 0 byte-identical files).

## Independent reruns at e43603c9

- Focused: `pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q` →
  **201 passed, 3 skipped**; mypy on the two changed production modules →
  "no issues found in 2 source files". All ten prospective tests named by
  the issue body are present in `test_admission_codec.py` (40 tests in the
  file). Live interface probe: `AdmissionDecodeCode` is exactly the six
  specified values; `AdmissionRowHeader` is frozen (FrozenInstanceError on
  mutation) and slotted; `decode_admission_header`, `decode_admission_record`,
  `encode_admission_record` present; a malformed legacy row raises
  `AdmissionRowDecodeError` (a `ValueError`) whose message contains neither
  the owner token nor any snapshot text and whose exception chain is
  suppressed (`__cause__ is None`, `__suppress_context__ is True`).
- CI `test` job, every leg re-run fresh with the workflow's exact arguments
  (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1` where the job sets them):
  server+turing+turing/backend+design → **1417 passed, 9 skipped** (50s);
  ext-harness+ext-sdk → **420 passed** (12s); root
  `tests/ --ignore=tests/tools/registry` → **4971 passed, 129 skipped**
  (4m49s); hive-conductor backend → **3626 passed, 19 skipped** (2m35s);
  one-process leakage proof `tests/ packages/hive-conductor/backend/tests
  packages/maistro-design/tests -q --timeout=60` → **9262 passed,
  149 skipped** (8m38s). The lane brief's `test: failure` is stale at this
  head — consistent with the captured GitHub check-run set for PR #1945 head
  `d9ea4f3b1671`, where the `test` check run is **success** and the only
  failure is `exact-debt-ledger`.
- Frontend legs of the same job: hive-conductor `npm run lint` → 0 errors
  (94 warnings), `npm run build` → success; generated-API-types gate
  (`dump-hive-openapi.py` + `gen:api` + `git diff --exit-code`) → **no
  diff**; canvas `npm run test:ci` → **79 passed**, `npm run lint` → 0
  errors (13 warnings), `npm run build` → exit 0, `npm audit
  --audit-level=high` → 0 vulnerabilities.
- Quality gates: `check-suite-inventory.py` (full, CI form) → 17 suites
  match; `check-test-duplicates.py` → 0 byte-identical groups;
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI exact args) → exit 0, 1323 = 1323;
  `check-reachability.py` → 1394 modules, 171 unreachable, exit 0;
  `check-reachability-dispositions.py` → 50 groups cover all 171, exit 0;
  `check-promotion-surface.py` → ok; `check-shipped-surface-truth.py` →
  matrix complete.

## Exact-debt-ledger residual (unchanged, external)

`RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py` fails with
exactly the two known findings — `check-reachability-provenance.py`:
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are
"NEW unreachable module absent from trusted base and not previously
authorized"; `check-reachability-dispositions-provenance.py`: the same two
as "NEW disposition absent from trusted ledger and not covered by an
already-landed reachability authorization". `origin/develop` is still
`4aa68edc0b6b` (branch 0 behind / 123 ahead, re-fetched this round), so the
required base-side grant has not landed. Structural cause re-read in source
this round: `scripts/ratchet_provenance.py:478 load_authorizations` reads
`quality/ratchet-authorizations.json` **from the base revision** — "a new
grant does not take effect in the change that introduces it" (two-merge
rule). The issue body forbids "baseline/grant/gate modifications to make an
unwired slice green", and this lane holds no GitHub write authority, so the
resolution stays external: land the reachability authorizations on the
integration base first, then merge the base into `auto-1893`. Unchanged
across 86cf62ae → be3316db → bb432f91 → 633281a → this round. The vulture
leg of exact-debt-ledger needs no amendment: 1323 = 1323 with CI's exact
scan arguments.

## Durability re-proof on a fresh disposable PostgreSQL 18

New container `b2verify2-pg` (`pgvector/pgvector:pg18` = PostgreSQL **18.6**,
127.0.0.1:55993, db `b2probe`), used for nothing else, removed after
evidence capture:

1. Destructive-first ordering per the issue: `pytest
   tests/migrations/test_migration_chain.py` on the raw server →
   **18 passed** (57s), chain and downgrade proven before any runtime use.
2. `alembic upgrade head` → real chain 001 → `062` (`alembic current`:
   `062 (head)`).
3. `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=postgresql://…@127.0.0.1:55993/b2probe
   MAISTRO_TEST_DATABASE_URL=postgresql+asyncpg://…@127.0.0.1:55993/b2probe`
   (same DB, both nonempty, server identity compared by the test) over
   `packages/maistro-core/tests/runs/test_root_admission_identity.py` +
   `tasks/test_admission_codec.py` → **204 passed, 0 skipped** (1.63s): the
   raw-asyncpg-vs-production-pool codec leg ran live against the migrated
   schema for unbound/bound/acknowledged states.
4. `pg_get_constraintdef` for `ck_task_idempotency_v2_identity` read live
   contains exactly the clause asserted at `test_admission_codec.py:134-137`:
   `((task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND run_id
   IS NOT NULL AND task_id = receipt_id))`, plus `acknowledged_at` ⇒ bound
   pair — the storage contract `encode_admission_record` writes against is
   enforced by the schema, not only by the codec.
5. Negative probe on the live DB: a direct SQL INSERT built by
   `encode_admission_record` with `task_id = 'task-mismatch' ≠ receipt_id`
   and both binding columns set → **rejected by the CHECK**
   (`violates check constraint "ck_task_idempotency_v2_identity"`).
6. Post-run residue: `SELECT count(*) FROM task_idempotency` → **0 rows**.

## Verdict inputs

- All issue-B2 acceptance criteria re-proven at this head except the
  merge-queue provenance leg, whose failure is the documented external
  two-merge residual above — not reproducible in-branch by any permitted
  action of this lane.
- CI `test: failure` (the named gate failure for this round): not
  reproducible; every leg of the named job re-ran fresh and green at
  e43603c9.
