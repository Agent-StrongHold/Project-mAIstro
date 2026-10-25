# #1893 verification round — job a53d6856

Snapshot: issue #1893 only; assigned branch `auto-1893`, clean starting HEAD
`e75dc6865e3e14fd2950a62a2b25d7907db0de13` (three docs-only commits ahead of
`1584201b`, the dispatch-context PR head), supplied develop base
`0d49d4e068de9ecbf0f9510e33781dba8abc87de`. Evidence sources: job
`a53d685662d34e0f8ea043041af530ba` driver logs check-0..4, the prior result
artifact `292953bdcc654fa5a4fd64ef25fa0c93/result.json`, and this round's own
reruns. One read-only `git fetch origin`: **origin/develop still resolves to
`0d49d4e068de`** (no commits since the supplied base), so there is no merge to
perform and the reachability authorization is still absent from the trusted
base.

No production code, ledger, grant, gate or test file was edited this round.
Every prior claim was rerun against reachable behavior; the named CI gate
failure (`test: failure`) was refuted again with the workflow's exact legs and
environment, and the durability/regression claims were re-proven independently
of the prior round's evidence.

## Environment hazard found and corrected

Driver check-0 (`uv sync --locked --extra dev`) **uninstalled
`maistro-bootstrap`** from the worktree venv (visible in check-0.log). This
round restored the CI `test` job's exact environment with
`uv sync --locked --extra dev --extra bootstrap` (it reinstalled
maistro-bootstrap==0.9.0). Local runners that sync without `--extra bootstrap`
run a different environment than the required `test` job — a plausible local
source of spurious `test` failures that do not exist in CI.

## Rerun evidence at this head

- Source SHA verified: `git rev-parse HEAD` =
  `e75dc6865e3e14fd2950a62a2b25d7907db0de13`, worktree clean before this note.
- Lint/type: `uv run ruff check .` → clean; `uv run ruff format --check .` →
  3238 files formatted; `uv run mypy packages/maistro-core/src` → no issues in
  775 source files.
- Focused suites, default env: `uv run pytest
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` →
  **201 passed, 3 skipped** (matches driver check-3).
- CI `test` job legs — every leg of `.github/workflows/ci.yml`'s `test` job
  rerun with its workflow env (`REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`):
  `packages/maistro-server/tests` → **535 passed, 9 skipped**;
  `packages/maistro-turing/tests` → **210 passed**;
  `packages/maistro-turing/backend/tests` → **90 passed**;
  `packages/maistro-design/tests` → **572 passed, 1 skipped**;
  `packages/maistro-ext-harness/tests` → **273 passed**;
  `packages/maistro-ext-sdk/tests` → **147 passed**;
  `tests/ --ignore=tests/tools/registry` → **4951 passed, 128 skipped**
  in 6m41s. **The brief's `test: failure` is not reproducible at this head**;
  combined with the dispatch check-runs recording `test: success` for
  `1584201b`, the recorded failure is transient (runner/environment), not a
  candidate defect.
- Other required gates, CI-exact: `check-shipped-surface-truth.py` → pass;
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → pass, **1323 reviewed identities → 1323 findings**
  (no unbanked and no eliminated identity, so the CI-repair exception to amend
  `quality/vulture-baseline.json` finds nothing to amend);
  `check-promotion-surface-provenance.py` → pass; `check-radon-baseline.py` →
  pass (137 → 137); `check-suite-inventory.py` → pass (17 suites);
  `check-convergence-matrix.py` → pass (171 unreachable modules attributed).
- exact-debt-ledger step 1 (`check-ratchet-provenance.py`,
  `RATCHET_BASE_REV=origin/develop`) → **fail**, exit 1, via
  `check-reachability-provenance.py` (NEW unreachable modules
  `maistro.runs.admission_identity`, `maistro.tasks.admission_codec`) and
  `check-reachability-dispositions-provenance.py` (NEW disposition
  `runs-root-admission-contracts`), both because
  `quality/ratchet-authorizations.json` at merge base `0d49d4e068de` contains
  no reachability authorization for these modules. Unchanged from prior rounds
  and structural: the two-merge rule requires the authorization to land on
  develop first; origin/develop is unchanged; landing it is an integration
  action outside this writer's authority (no push, no gate modification, and
  #1893 itself forbids baseline/grant/gate edits to green an unwired slice).

## Independent live-PostgreSQL durability proof (fresh container, this round)

- Disposable `pgvector/pgvector:pg18` container (rootless Docker context),
  database `maistro_1893_a53d`, port 18932; container removed after the run.
- `DATABASE_URL=postgresql://maistro:…@127.0.0.1:18932/maistro_1893_a53d
  uv run alembic upgrade head` → real chain 001→061, exit 0, `alembic current`
  = `061 (head)`, including `055_task_admission_generations`.
- With `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both targeting
  that same DB and `MAISTRO_REQUIRE_PG_LEGS=1`: focused suites →
  **204 passed, 0 skipped** (the three skipped legs now executed:
  `test_raw_and_production_pool_codecs_read_identical_text_snapshots` across
  unbound/bound/acknowledged; each asserts distinct production/raw backend
  PIDs on one server+database identity and `persisted_admission_rows=1`).
- Constraint shape read back from `pg_constraint` in the migrated DB:
  `ck_task_idempotency_v2_identity` exists (contype 'c', exactly 1 row) and
  requires, for `format_version = 2`, non-null hex `generation_id`/`claim_token`,
  envelope scalars, `expires_at > created_at`, and exactly
  `((task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND run_id IS
  NOT NULL AND task_id = receipt_id))`. The repaired
  `encode_admission_record` (`admission_codec.py:291-292`) emits the pair
  together with `task_id = binding.receipt_id`, and
  `admission_identity.py:291-292` enforces
  `binding.receipt_id == envelope.receipt_id`, so the suite's three INSERT
  states satisfy the real migration CHECK — verified against the live catalog,
  not the migration's source text.
- Final `SELECT count(*) FROM task_idempotency` → **0 residue rows**.

## Regression replay: current tests fail against the pre-binding-fix codec

Loaded `git show c1351bffe^:packages/maistro-core/src/maistro/tasks/admission_codec.py`
(the revision before "preserve v2 admission binding storage identity", whose
encoder hardcodes `"task_id": None` even for bound records) into
`sys.modules` as `maistro.tasks.admission_codec` before in-process pytest
collection, then ran the **unchanged current** `test_admission_codec.py`:
**43 failed, 85 passed, 3 skipped**. Among the failures are exactly the
binding-identity tests that pass at HEAD:
`test_v2_round_trip_preserves_all_snapshot_bytes[bound]`,
`[acknowledged]`, and `test_v2_run_without_task_is_corruption_not_a_binding`
(plus the whitespace-normalization and non-UTF-8 families fixed by later
commits on this branch). The same file on the unchanged tree at HEAD:
**201 passed, 3 skipped** (204/0 with PG legs). The repairs fail against the
regressions they name and pass at this head; the injection harness is at
`/tmp/replay_prefix_codec.py` in the run environment (not committed; no tree
file was modified for the replay).

## Interface acceptance spot checks (read-only, this round)

- `admission_codec.py:127-135`: `AdmissionDecodeCode(StrEnum)` carries exactly
  the six required values; `:138` `AdmissionRowDecodeError(ValueError)`;
  `:156-157` `AdmissionRowHeader` is `@dataclass(frozen=True, slots=True)`;
  `:207/:233/:260` the three required functions with the required signatures.
- The ten prospective tests from the issue body all exist in
  `test_admission_codec.py` (lines 122, 160, 171, 187, 205, 220, 231, 262,
  294, 448).
- Branch diff vs `0d49d4e068de` remains decode-only: two new source modules,
  two new test files, `_vulture_whitelist.py`, the two quality rows,
  convergence-matrix `Unreachable` counts and inventory notes. No SQL
  mutation, HTTP mapping, queue or web serialization change; no production
  import of either new module (B2 scope).
- No premature-closure language introduced this round: this note and its
  commit reference #1893 without fixes/closes/resolves.

## Residual (unchanged from prior rounds, re-confirmed here)

1. exact-debt-ledger fails on reachability/disposition provenance until the
   authorization lands on `origin/develop` and develop is merged into this
   branch (two-merge rule). Documented, not circumvented; everything else at
   this head is green by direct execution.
2. Snapshot finite-number precision (`9007199254740993.0` parsed lossily by
   the #1851 dependency) remains a recorded coordinated dependency repair
   outside codec scope; not re-tested this round, no new claim.
