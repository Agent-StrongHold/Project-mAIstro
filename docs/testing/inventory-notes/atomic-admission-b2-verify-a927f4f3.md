---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job a927f4f3 (independent re-validation at f07c1e922; no develop movement)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`f07c1e922951aa8a311a49acb15bba8323f5eb9a` — byte-identical to the
previous round's end head. This round authors no production code, no
tests, no ledger rows, no grants and no gate files; the only tree change
is this note. Every prior claim was re-derived independently rather than
trusted: source interfaces were re-read against the issue text, and all
gates, suites and database probes below were executed fresh in this
round.

## Issue-acceptance re-derivation (source + tests, this head)

- `admission_codec.py` implements exactly the issue's shared interfaces:
  frozen/slotted `AdmissionRowHeader` with the six required fields
  (`admission_codec.py:157-205`); `decode_admission_header`
  (`:207`); `decode_admission_record` rejecting a header that disagrees
  with the row's scalars via structural comparison — `True==1` cannot
  launder a column (`:233-258`); `encode_admission_record` returning a
  fresh flat mapping that emits `task_id = binding.receipt_id` plus
  `run_id` together from the binding (`:260-294`); the six-code
  `AdmissionDecodeCode` StrEnum (`:127-135`); `AdmissionRowDecodeError`
  carrying `code` and a hex-validated `scope_key` with parsing chains
  suppressed (`:138-155`).
- `partial_legacy_binding` is yielded for receipt-only rows and
  announced-without-Run (one-sided pairs), and for bound pairs without
  receipt identity — never guessed into a binding
  (`admission_codec.py:567-645`).
- `AdmissionRecordV2.__post_init__` enforces
  `binding.receipt_id == envelope.receipt_id`
  (`admission_identity.py:291-293`).
- Scope vs develop re-verified: the branch diff touches only the two
  contract modules, `_vulture_whitelist.py`, the two test files,
  quality reachability baseline/disposition rows and docs — no SQL
  mutation, HTTP mapping or queue change.

## Live durability re-proof (fresh disposable DB, this round)

- Fresh database `maistro_1893_r2` created in disposable PG 18.6
  (`auto-1893-pg`, 127.0.0.1:15498); the real chain migrated 001→062
  via `alembic upgrade head` (69 revisions).
- Focused suites live: `test_root_admission_identity.py` +
  `test_admission_codec.py` with `MAISTRO_TEST_PG_DSN`,
  `MAISTRO_TEST_DATABASE_URL` (same DB) and `MAISTRO_REQUIRE_PG_LEGS=1`:
  **204 passed, 0 skipped** (non-PG run of the same files: 201 passed,
  3 skipped). The PG legs INSERT into and SELECT from the real
  `task_idempotency` table through both the production
  `_register_json_codecs` pool and an independent raw asyncpg pool,
  assert server identity and distinct backend PIDs, and delete their
  rows.
- `ck_task_idempotency_v2_identity` probed live at 062: the
  production-encoder shape (`task_id = receipt_id`, `run_id` set)
  INSERTs accept; `task_id != receipt_id`, `run_id` without `task_id`,
  `task_id` without `run_id`, and `acknowledged_at` without a full pair
  each violate the CHECK. Residue after cleanup: 0 rows.

## CI `test:` gate — not reproducible at this head

Every Python leg of the `test` job (`.github/workflows/ci.yml:496`)
re-executed fresh at this head, CI env (`REQUIRE_AUTH=false`,
`MAISTRO_DRY_RUN=1`):

- `packages/maistro-server/tests`: 557 passed, 8 skipped
- `packages/maistro-turing/tests`: 210 passed
- `packages/maistro-turing/backend/tests`: 90 passed
- `packages/maistro-design/tests`: 572 passed, 1 skipped
- `packages/maistro-ext-harness/tests`: 273 passed
- `packages/maistro-ext-sdk/tests`: 147 passed
- `tests/ --ignore=tests/tools/registry`: 4971 passed, 129 skipped
- cross-suite leakage proof (one process, `--timeout=60`): 9262 passed,
  149 skipped

The npm legs carry from develop: the diff vs `origin/develop` contains
zero frontend and zero `maistro-server` files, so the committed
`types.gen.ts` cannot drift and prior rounds re-ran the npm legs fresh
on this identical content. Supporting gates also green: ruff check,
ruff format --check (3277 files), canonical mypy (894 files, 0 issues),
`check-suite-inventory.py` (17 suites, 31333 node IDs),
`check-test-duplicates.py` (0 duplicates).

## exact-debt-ledger residual — unchanged and external

With CI-exact arguments and `RATCHET_BASE_REV=origin/develop`:

- vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): exit 0, 1323 reviewed identities = 1323
  findings; no amendment needed or made.
- `check-shipped-surface-truth.py`: pass.
- `check-reachability.py` / `check-reachability-dispositions.py`
  (candidate-side): pass — all 171 unreachable modules dispositioned
  (50 groups).
- `check-ratchet-provenance.py`: **exit 1, reachability only** —
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
  are NEW unreachable modules whose branch-side baseline/disposition
  rows cannot self-authorize. Re-verified this round: `origin/develop`
  is still `435dc1937e04` (0 commits ahead) and its
  `quality/ratchet-authorizations.json` carries 11 rows, none for
  admission identities. The gate reads authorizations from the merge
  base by design (two-merge rule), and issue #1893 explicitly forbids
  baseline/grant/gate modifications to make an unwired slice green —
  so no in-lane repair exists that does not violate the issue. The
  documented resolution stands: land the reachability authorization on
  develop first, then merge develop into this branch. Blocking again
  on that external coordination item, with everything else proven.
