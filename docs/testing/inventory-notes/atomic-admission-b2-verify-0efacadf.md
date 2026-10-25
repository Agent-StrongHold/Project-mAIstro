---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job 854161adf679 (develop-sync merge round)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`0efacadf306ba8f53262125a86fd9a91c8a1af5d` — the branch merged `origin/develop`
`bb4257f0960f` (merge commit `0efacadf3`, PR #1945 head). The merge delta on
the first parent is exactly `runs/pg_store.py` + two new PG test modules +
docs from develop #2114; **no frontend file changed**. No production code,
ledger, grant or gate was edited this round: independent verification pass
with one added evidence note.

## The named CI gate "test: failure" — disproven at this head

Live GitHub evidence gathered fresh this round (read-only API):

- All completed `ci.yml` runs on `auto-1893`: `d9ea4f3b1` success,
  `943db286d` success; run 38062467384 at THIS head concluded **success**
  (`test` job completed success at 2026-10-10T15:30:00Z, attempt 1). No
  `merge_group` run exists for pr-1945. No completed "test: failure" row is
  reachable for this branch at any head.
- Final check-run state at `0efacadf306b`: every check success or skipped
  except **exact-debt-ledger: failure** (the known external residual, below).

Every leg of the CI `test` job was additionally re-executed fresh at this head
(CI env `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`): server 545+8sk, turing 210,
turing/backend 90, design 572+1sk, ext-harness 273, ext-sdk 147, root
`tests/ --ignore=tests/tools/registry` 4971+129sk, hive-conductor backend
3626+19sk, one-process leakage (`tests/` + hive backend + design in one
process, `--timeout=60`) 9262+149sk, suite inventory 17 suites ok (31266 node
IDs), test duplicates 0. OpenAPI types step: `dump-hive-openapi.py` (228
paths/134 schemas) + `npm run gen:api` + `git diff --exit-code
types.gen.ts` → no diff. npm legs carry over by content identity: both
frontend trees are byte-identical to `d9ea4f3b1`, whose CI run succeeded.

## exact-debt-ledger with CI's exact arguments (fresh at this head)

- vulture leg: `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1323 reviewed identities = 1323 findings,
  exit 0. **No vulture-baseline.json amendment needed or made.**
- shipped-surface leg: complete, exit 0.
- provenance leg (`RATCHET_BASE_REV=origin/develop
  check-ratchet-provenance.py`): FAIL, identical to the CI log for this head —
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`:
  NEW disposition/baseline rows "absent from trusted base and not previously
  authorized". `origin/develop` re-fetched this round is still `bb4257f0960f`,
  which lacks the reachability authorization. Two-merge rule: the grant must
  land on develop first; the lane brief's ledger exception covers the vulture
  ledger only, and the issue forbids "baseline/grant/gate modifications to
  make an unwired slice green". No permitted in-lane action changes this;
  unblock = owner lands the reachability grant on develop, then this branch
  merges develop. (No grant vehicle PR exists in the snapshot; #2109 is an
  unrelated design-regex draft.)

## B2 acceptance, re-proven live at this head

- Interfaces (live probe): `AdmissionRowHeader` frozen **and** slotted with
  exactly the 6 specified fields; `AdmissionDecodeCode` StrEnum with exactly
  `unsupported_schema, unsupported_format, invalid_header, invalid_snapshot,
  invalid_v2_record, partial_legacy_binding`; `decode_admission_header`,
  `decode_admission_record`, `encode_admission_record` present;
  `AdmissionRowDecodeError` is a `ValueError` subclass carrying `code` +
  validated-hash `scope_key`.
- Error hygiene (live poisoned-row probe against the real decode path):
  snapshot containing a secret owner token + bare `NaN` → `invalid_snapshot`,
  message contains no secret and no snapshot bytes, `__cause__ is None`,
  `__suppress_context__ True` (`raise … from None` at all parse sites).
- Binding repair re-read at HEAD: `admission_codec.py` emits `task_id` =
  `binding.receipt_id` and `run_id` = `binding.run_id` together;
  `admission_identity.py` rejects `binding.receipt_id !=
  envelope.receipt_id`; `test_admission_codec.py` asserts the migration-055
  CHECK shape (`task_id == "rcpt-1"`, `run_id == "run-1"`) independently of
  encode/decode agreement.
- All 10 prospective tests named in the issue: present 1:1 in
  `test_admission_codec.py` (grep `def <name>` = 1 each).
- mypy on both new modules: "no issues found in 2 source files".
- Focused pytest: 201 passed, 3 skipped (PG legs skip without DSN).

## Disposable-PG durability (fresh, this round)

`pgvector:pgvector:pg18` container, PostgreSQL 18.6, dedicated DB on
127.0.0.1:15499; `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both
set to that same DB:

1. Destructive-first contract: `tests/migrations/test_migration_chain.py`
   → **18 passed** (walks 001→head and reverses).
2. `alembic upgrade head` → at **062 (head)**.
3. Focused admission suites with `MAISTRO_REQUIRE_PG_LEGS=1`:
   **204 passed, 0 skipped**.
4. Live CHECK probe on the migrated schema: `ck_task_idempotency_v2_identity`
   present (verified via `pg_constraint`); a bound v2 row with
   `task_id = receipt_id`, `run_id` set, `acknowledged_at` set is ACCEPTED;
   a partial pair (`task_id` only) is REJECTED by the CHECK; a
   `task_id <> receipt_id` row is REJECTED by the CHECK.
5. Residue: 0 rows in `task_idempotency` after the suites and after probe
   cleanup.

Operator note: an initial "3 failed" during this round was this worker's own
shell quoting bug (`MAISTRO_TEST_PG_DSN="$DATABASE_URL"` expanded before
`DATABASE_URL` was assigned in the same `export` list, emptying the DSN) —
re-run with literal DSNs gave 204/0. First CHECK probe attempts used a 64-char
claim_token and an explicit NULL `completed_at`; the schema requires 32-hex
`claim_token` and `completed_at NOT NULL DEFAULT 0` (server default), so the
probe, not the product, was wrong. Recording both so the residue is auditable.

## Premature-closure scan

No `fixes/closes/resolves #1893` in any commit subject/body on the branch;
PR #1945 body says "Refs #1893" only.
