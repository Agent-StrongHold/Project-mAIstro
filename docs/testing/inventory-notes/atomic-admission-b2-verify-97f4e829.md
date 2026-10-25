---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job d493fb504f61 (repair)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`97f4e829f9410b0f471ec6a13200e5f350c910b3`. Delta vs the previously verified
head `e43603c901a6` is exactly one docs-only commit (the e43603c9 evidence
note), so functional code is identical to the last fully verified head; every
leg below was nevertheless re-executed fresh at this head, not inherited.
`origin/develop` has moved since the last round: `4aa68edc0b6b` → `bb4257f0960f`
(two new WIP commits #2114/#2115 touching `runs/pg_store.py` + two test files
+ two inventory notes — no overlap with this branch's files), re-fetched this
round. The branch was **not** merged with the new develop: the lane's merge
instruction is conditional on a develop-sync conflict, which did not occur,
and the new develop still lacks the reachability grant (checked directly), so
a merge would not change the exact-debt-ledger outcome (below).

No production code, ledger, grant, gate or test file was edited this round:
independent verification pass with one added evidence note.

## Driver logs (job d493fb504f61, check-0..4) and the prior job

Prior job 89ca9249 failed with `provider_error` (model request timeout) after
**all five** of its checks had already returned 0 (uv sync, ruff check, ruff
format --check, focused admission pytest 201+3sk, suite-inventory) — a driver
failure, not a validation failure. This job's own check-0..4 all pass: uv sync
ok; `ruff check .` "All checks passed!"; `ruff format --check .` 3270 files
already formatted; focused admission pytest **201 passed, 3 skipped** (the 3
skips are the PG legs before a DSN is configured); suite-inventory ok (16401
identities, 0 duplicates).

## Independent reruns at 97f4e829f941

- Interface probe (live): `AdmissionDecodeCode` is a `StrEnum` with exactly the
  six specified values; `AdmissionRowHeader` is frozen **and** slotted with
  exactly `scope_key, format_version, fingerprint, created_at_us,
  expires_at_us, lease_expires_at_us`; `decode_admission_header`,
  `decode_admission_record`, `encode_admission_record` all present;
  `AdmissionRowDecodeError` subclasses `ValueError`. Error-hygiene probe on a
  poisoned v2 row (owner token `SECRET-OWNER-TOKEN` and receipt snapshot
  `RECEIPT-SECRET` inside a malformed request snapshot): raised
  `AdmissionRowDecodeError` with message containing **neither** secret,
  `scope_key` exposed as the validated 64-char hash only, and the chain fully
  suppressed (`__suppress_context__=True`, `__cause__ is None`,
  `__context__ is None`).
- All ten prospective tests named by the issue body are present (1:1) in
  `test_admission_codec.py`. mypy on the two changed production modules →
  "Success: no issues found in 2 source files".
- Repaired locations re-read at this head: `admission_codec.py:291-292` emits
  `task_id`/`run_id` together from the binding (both-or-neither);
  `admission_identity.py:291-292` raises when `binding.receipt_id !=
  envelope.receipt_id`; `test_admission_codec.py:134-137` asserts the
  migration-055 CHECK shape independently of codec round-trip agreement.
- CI `test` job, every leg re-run fresh with the workflow's exact arguments:
  server+turing+turing/backend+design → **1417 passed, 9 skipped** (49s);
  ext-harness+ext-sdk → **420 passed** (11s); root
  `tests/ --ignore=tests/tools/registry` → **4971 passed, 129 skipped**
  (4m40s); hive-conductor backend → **3626 passed, 19 skipped** (2m35s);
  one-process leakage proof `tests/ packages/hive-conductor/backend/tests
  packages/maistro-design/tests -q --timeout=60` → **9262 passed,
  149 skipped** (7m36s). Counts identical to the prior round's independent
  run at e43603c9. The captured GitHub check-run set for PR #1945 head
  `d9ea4f3b1671` shows `test` **success** and `exact-debt-ledger` failure;
  the captured `test: failure` rows belong to PR #1855 head `3f2c79a70d9e`
  (a different PR, together with its own SAST/Coverage-gate failures).
- Frontend legs of the same job: hive-conductor `npm run lint` → 0 errors
  (94 warnings), `npm run build` → success; generated-API-types gate
  (`dump-hive-openapi.py` + `gen:api` + `git diff --exit-code`) → **no diff**
  (tree clean afterwards); canvas `npm run test:ci` → **79 passed** (5 files),
  `npm run lint` → 0 errors (13 warnings), `npm run build` → exit 0,
  `npm audit --audit-level=high` → **0 vulnerabilities**. Lockfiles are
  unchanged vs develop, so `npm ci` re-runs were not needed for equivalence.
- Quality gates (CI forms): `check-suite-inventory.py` full → 17 suites match;
  `check-test-duplicates.py` → 0 byte-identical groups;
  `check-shipped-surface-truth.py` → matrix complete;
  `check-reachability.py` → 1394 modules, 171 unreachable, exit 0;
  `check-reachability-dispositions.py` → 50 groups cover all 171, exit 0;
  `check-promotion-surface.py` → ok; ruff check/format → clean.

## Exact-debt-ledger residual (unchanged, external)

`RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py` re-run this
round: fails with exactly the two known findings —
`check-reachability-provenance.py`: `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` are "NEW unreachable module absent from
trusted base and not previously authorized";
`check-reachability-dispositions-provenance.py`: the same two as "NEW
disposition absent from trusted ledger and not covered by an already-landed
reachability authorization". Mechanism re-read in source this round:
`scripts/check-reachability-provenance.py` calls
`prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)` — the
authorization must exist on the **merge base** (two-merge rule), so the
candidate's own `quality/reachability-baseline.json` rows bank the debt but
cannot authorize it. `origin/develop` = `bb4257f0960f` (re-fetched this
round) contains **no** `admission_identity`/`admission_codec` entries in
`reachability-baseline.json`, `reachability-dispositions.json` or
`ratchet-authorizations.json`, so the grant still has not landed and merging
develop now would not change the outcome. The vulture leg of
exact-debt-ledger needs no amendment:
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` (CI exact args) → **exit 0**, 1323 reviewed = 1323
findings. Resolution stays external (owner lands the reachability
authorizations on the integration base, then the base merges into
`auto-1893`); no permitted in-lane action can produce it, and the issue body
forbids "baseline/grant/gate modifications to make an unwired slice green".

## Durability re-proof on a fresh disposable PostgreSQL 18

New container `b2r1893-pg` (`pgvector/pgvector:pg18` = PostgreSQL **18.6**,
127.0.0.1:55977, db `b2probe`), used for nothing else, removed after evidence
capture:

1. Destructive-first ordering per the issue: `pytest
   tests/migrations/test_migration_chain.py` on the raw server (plain
   `postgresql://` URL, as the chain test requires) → **18 passed** (53s),
   chain and downgrade proven before any runtime use.
2. `alembic upgrade head` with `DATABASE_URL` set → real chain, `alembic
   current` → **062 (head)**.
3. `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=postgresql://…@127.0.0.1:55977/b2probe
   MAISTRO_TEST_DATABASE_URL=postgresql+asyncpg://…@127.0.0.1:55977/b2probe`
   (same DB, both nonempty) over
   `packages/maistro-core/tests/runs/test_root_admission_identity.py` +
   `tasks/test_admission_codec.py` → **204 passed, 0 skipped** (1.57s): the
   raw-asyncpg-vs-production-pool codec leg ran live against the migrated
   schema for unbound/bound/acknowledged states.
4. `pg_get_constraintdef` for `ck_task_idempotency_v2_identity` read live
   contains exactly the binding clause asserted at
   `test_admission_codec.py:134-137`: `((task_id IS NULL) AND (run_id IS
   NULL)) OR ((task_id IS NOT NULL) AND (run_id IS NOT NULL) AND (task_id =
   receipt_id))`, plus `acknowledged_at IS NULL OR (task_id IS NOT NULL AND
   run_id IS NOT NULL)` — the storage contract `encode_admission_record`
   writes against is enforced by the schema, not only by the codec.
5. Negative probe on the live DB: a row built by `encode_admission_record`
   with `task_id = 'task-mismatch' ≠ receipt_id` → **rejected by the CHECK**
   (`CheckViolationError ... violates check constraint
   "ck_task_idempotency_v2_identity"`).
6. Post-run residue: `SELECT count(*) FROM task_idempotency` → **0 rows**.

## Verdict inputs

- All issue-B2 acceptance criteria re-proven at this head except the
  merge-queue provenance leg, whose failure is the documented external
  two-merge residual above — not reproducible in-branch by any permitted
  action of this lane.
- CI `test: failure` (the named gate failure for this round): not
  reproducible; every leg of the named job re-ran fresh and green at
  97f4e829f941. The failure rows in the dispatch snapshot belong to the
  linked PR #1855 head, not to this branch's PR.
