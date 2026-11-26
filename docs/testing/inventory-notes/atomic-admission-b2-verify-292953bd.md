# #1893 verification round — job 292953bd

Snapshot: issue #1893 only; assigned branch `auto-1893`, clean starting HEAD
`1584201b36138fde646736eb74497fdfb851b0f5`, supplied develop base
`0d49d4e068de9ecbf0f9510e33781dba8abc87de`. Evidence sources: job
`292953bdcc654fa5a4fd64ef25fa0c93` dispatch snapshot and check-0..4 logs, the
prior result artifact `399ed78757e14dc7b2b12cb473137809/result.json`, and this
round's own reruns. No remote re-enumeration beyond one read-only
`git fetch origin` (origin/develop still resolves to `0d49d4e068de`, so the
supplied base is current and there is no merge to perform).

No production code, ledger, grant, gate or test file was edited this round.
The round is verification plus this note: every prior claim was rerun against
reachable behavior, and the named CI gate failures were reproduced or refuted
with the workflow's exact commands.

## Rerun evidence at this head

- Source SHA verified: `git rev-parse HEAD` =
  `1584201b36138fde646736eb74497fdfb851b0f5`, worktree clean before this note.
- Focused suites, default env: `uv run pytest
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` →
  **201 passed, 3 skipped** (matches driver check-3).
- Lint/type: `uv run ruff check .` → clean; `uv run ruff format --check .` →
  3238 files formatted; `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py` → no issues.
- Live PostgreSQL: `createdb maistro_1893_292953bd`, then
  `DATABASE_URL=postgresql:///maistro_1893_292953bd uv run alembic upgrade
  head` → real chain 001→061 (local PG 18.6 cluster), including 055. With
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both pointing at that
  DB and `MAISTRO_REQUIRE_PG_LEGS=1`: **204 passed, 0 skipped**. JUnit
  properties record three production (registered-codec pool) and three raw
  asyncpg sessions, backend PIDs 871023–871028, all connected to
  `maistro_1893_292953bd` over the Unix socket; `persisted_admission_rows=1`
  on each of the six legs (three v2 binding states × two pool kinds); final
  `SELECT count(*) FROM task_idempotency` → **0 residue rows**.
- Constraint shape: `pg_constraint` in the migrated DB defines
  `ck_task_idempotency_v2_identity` requiring, for `format_version = 2`,
  non-null hex `generation_id`/`claim_token`, envelope scalars, and exactly
  `((task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND run_id IS
  NOT NULL AND task_id = receipt_id))` — the same shape
  `encode_admission_record` emits (`admission_codec.py` binding emits
  task_id+run_id together with `task_id = receipt_id`), so the repair's
  storage round-trip satisfies the real migration, not a test local fake.
- Regression replay (pre-fix decoder): loaded
  `git show f9e5b5911^:packages/maistro-core/src/maistro/tasks/admission_codec.py`
  into an in-memory module ahead of collection via a /tmp pytest plugin and
  ran `-k 'excessive_snapshot_nesting or
  legacy_bound_evidence_rejects_whitespace'` → **8 failed, 8 passed**
  (four leaked `RecursionError`, four whitespace-corrupted task ids accepted),
  then the same selection on the unchanged tree → **16 passed**. The
  whitespace and recursion repairs (`f9e5b5911`) are real, and the tests fail
  against the regression they name.
- CI `test` job legs, workflow env (`REQUIRE_AUTH=false`,
  `MAISTRO_DRY_RUN=1`): `packages/maistro-server/tests
  packages/maistro-turing/tests packages/maistro-turing/backend/tests
  packages/maistro-design/tests packages/maistro-ext-sdk/tests -q` →
  **1554 passed, 10 skipped**; `tests/ --ignore=tests/tools/registry -q` →
  **4951 passed, 128 skipped** in 6m27s. The brief's `test: failure` is not
  reproducible at this head and the captured check-runs for
  `1584201b` record `test: success`; the only failing check at this head is
  `exact-debt-ledger`.

## exact-debt-ledger: two of three steps pass, the third is two-merge blocked

Run with CI's exact arguments from `.github/workflows/vulture-ratchet.yml`:

- `uv run python scripts/check-shipped-surface-truth.py` → **pass**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **pass**,
  1323 reviewed identities → 1323 findings, all classified, `unclassified: 0`.
  No unbanked identity and no eliminated identity: the CI-repair exception to
  amend `quality/vulture-baseline.json` finds nothing to amend, so the ledger
  is left untouched.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` → **fail**, exactly as prior rounds
  recorded: `check-reachability-provenance.py` rejects
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` as NEW
  unreachable modules, and `check-reachability-dispositions-provenance.py`
  rejects the `runs-root-admission-contracts` disposition covering them, in
  both cases because `load_authorizations('reachability',
  base=merge-base(origin/develop, HEAD))` — `quality/ratchet-authorizations.json`
  at `0d49d4e068de` — contains no entry for these modules.

This is the two-merge rule working as designed, not a candidate defect: the
branch banks the debt (`quality/reachability-baseline.json` rows and the
disposition) and the authorization must pre-exist on `origin/develop` before
any content merge can pass. `origin/develop` is unchanged at the supplied
base, so the blocker stands. All in-branch "fixes" are prohibited or useless:
wiring the modules would violate #1893's own scope (B2 forbids any consumer,
live `_assess` change, SQL mutation or HTTP mapping — C is the consumer);
deleting the banked baseline rows/disposition leaves the gate failing (the
modules are genuinely unreachable) with an inconsistent candidate; a
branch-side grant cannot authorize itself because the loader reads the base.
Resolution requires landing the reachability authorization on develop first,
then merging develop into this branch — an integration action outside this
writer's authority.

## Interface acceptance spot checks (read-only)

- `AdmissionDecodeCode` carries exactly the six required values;
  `AdmissionRowDecodeError` validates `scope_key` against `[0-9a-f]{64}` and
  nulls it otherwise; every raiser suppresses its parsing chain
  (`from None`, 25 sites); messages name column and failure class only.
- `decode_admission_record` re-derives the header under the same strict
  validation and rejects disagreement structurally (`True == 1` cannot
  launder a column), before any format branch — an unknown format can never
  fall through to legacy.
- The module contains no `hashlib`/`sha256`/fingerprint computation: stored
  fingerprints are validated as shape only and never recalculated, per the
  snapshot-encoding contract.
- Receipt-only and announced-without-Run legacy rows are asserted
  `PARTIAL_LEGACY_BINDING` (`test_legacy_receipt_only_row_is_partial_not_unbound`,
  `test_legacy_bound_pair_without_receipt_is_partial_never_fabricated`),
  distinct from unbound, with the header's fingerprint/expiry preserved by
  dedicated tests.
- Branch diff remains decode-only: four source/test files, `_vulture_whitelist`,
  the quality rows, convergence-matrix `Unreachable` counts and inventory
  notes; no SQL mutation, HTTP mapping, queue or web serialization change.

## Residual (unchanged from prior rounds, unchanged here)

1. exact-debt-ledger fails on reachability/disposition provenance until the
   authorization lands on `origin/develop` (two-merge rule); documented, not
   circumvented.
2. Snapshot finite-number precision: `CanonicalJsonObject` (the #1851
   dependency) parses `9007199254740993.0` lossily via float; recorded by the
   earlier round as a coordinated dependency repair outside codec scope. This
   round did not re-test it and makes no claim either way beyond that record.
