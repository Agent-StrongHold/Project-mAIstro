# Verification round at 66c43a051 — #1893 B2 admission codec

inventory-delta:
  suite: packages/maistro-core/tests
  baseline: 16567
  after: 16567
  delta: 0
  reason: "no test files added, removed, or renamed this round; docs-only commit"

## Scope of the round

Focused re-validation of the `auto-1893` head `66c43a051dc8d093c6dfcc468007d408938b92bd`
after the dispatch flagged `test: failure` and the exact-debt-ledger repair. No
source file was modified this round; every check below was executed fresh at this
head.

## Gate evidence gathered this round

- Live merge-queue state at remote head `80171ce1cff9` (read-only `gh run list`):
  CI **success** (the `test` job passed), quality **success**, Vulture Ratchet
  **failure** — the only red workflow — failing in job `exact-debt-ledger` at the
  step `Require enforced ratchet provenance policy` (run 38912209012).
- `test: failure` disproven at HEAD: `uv run pytest tests/ --ignore=tests/tools/registry -q`
  → **4982 passed, 135 skipped** (CI leg 7, CI-exact args). CI legs 1–6 run
  `maistro-server/turing/turing-backend/design/ext-harness/ext-sdk` tests; the
  branch's non-docs footprint contains none of those packages (verified:
  `git diff --name-only origin/develop..HEAD` = maistro-core admission modules +
  their tests + `_vulture_whitelist.py` + 2 quality ledger files).
- exact-debt-ledger, remaining two steps at HEAD:
  `uv run python scripts/check-shipped-surface-truth.py` → exit 0;
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → exit 0, **1322 reviewed identities = 1322 findings** — no unbanked identity,
  so the CI-repair-round ledger amendment has no target; `quality/vulture-baseline.json`
  untouched.
- Ratchet provenance (CI step, CI-equivalent env):
  `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
  → exit 1 on exactly `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` ("NEW ... not previously authorized"). Every
  other ratchet in the same run is OK. Base resolution without the env var
  converges on the same trusted base `ab8b3737`.
- Two-merge wall re-proven: `git merge-base --is-ancestor 3235229f5fed origin/develop`
  → NO; origin/develop is still `ab8b3737` (fetched this round) and is already
  merged into this branch (`255e02e34`), so a further develop merge delivers
  nothing new until the owner lands the reachability grant on develop.
- Real-database durability at this head (the one acceptance item left unverified
  in the previous round's report): disposable `pgvector/pgvector:pg18` container,
  `DATABASE_URL=... uv run alembic upgrade head` → chain 001→063 exit 0;
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=...
  uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py -q`
  → **349 passed, 0 skipped**. Live storage contract on the migrated chain:
  `ck_task_idempotency_v2_identity` exists; a fully valid format-2 row whose only
  defect is `task_id <> receipt_id` is rejected by the CHECK, while the identical
  row with `task_id = receipt_id` inserts; table truncated afterwards
  (`count(*) = 0`).
- `uv run mypy packages/maistro-core/src` → Success, 791 files.
  `uv run python scripts/check-retired-guidance.py` → exit 0 (471 files).
  Driver checks at this head: ruff check exit 0, ruff format --check exit 0,
  focused pytest 346 passed 3 skipped (pure mode), check-suite-inventory exit 0
  (17 suites, 16567 identities).

## Residual blocker (unchanged, structural)

The `exact-debt-ledger` provenance step cannot pass until the reachability grant
for the two admission rows is authorized from the trusted base — i.e. the grant
must land on `origin/develop` first (two-merge rule; `ratchet_provenance.py`
reads `quality/ratchet-authorizations.json` from the merge base), after which
merging origin/develop into `auto-1893` resolves the gate. Issue #1893 forbids
in-branch baseline/grant edits that would green an unwired slice, and an
in-branch grant could not authorize itself regardless. This is a develop-side
action outside worker authority.
