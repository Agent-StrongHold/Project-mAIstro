---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair round — job 9ecca364 (independent re-validation at 733499272; sole residual remains the external two-merge grant)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`73349927284f831fa0867e6dd418c7c9c0aa3b45` (exact dispatch head). This
round authors no production code, no tests, no ledger rows, no grants
and no gate files; the only tree change is this note. Nothing was
trusted from earlier rounds: every gate, suite and database probe below
was executed fresh in this round at this head.

## Dispatched CI failures — `test: failure`

The prior job (`e57f2680`) failed on a **provider timeout
(`provider_error`), not on any check**: its own `result.json` records
returncode 0 on all five deterministic checks (uv sync, ruff check,
ruff format --check, focused admission suites 201 passed 3 skipped,
suite inventory ok). This round re-proved the dispatched failure absent:

- `git diff e519c6dfcf41..HEAD -- . ':(exclude)docs'` is **empty** —
  zero non-docs delta against the CI-evaluated head where `test` =
  success (20m58s) was re-read from check runs.
- Every Python leg of the CI `test` job re-run fresh at this head with
  the job's env (`REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`): server
  557 passed 8 skipped; turing 210; turing backend 90; design 572
  passed 1 skipped; ext-harness 273; ext-sdk 147; root
  `tests/ --ignore=tests/tools/registry` 4971 passed 129 skipped.
- OpenAPI no-diff: `scripts/dump-hive-openapi.py` then
  `git diff --exit-code -- packages/hive-conductor/frontend/src/api/types.gen.ts`
  → clean (backend schema untouched by the branch; the npm legs carry
  by content identity from the CI-green head).

## Issue acceptance re-proven at this head

- Interfaces re-read from source, not from prior notes:
  `AdmissionRowHeader` is `@dataclass(frozen=True, slots=True)` with the
  exact six fields and `format_version: Literal[1, 2]`;
  `AdmissionDecodeCode(StrEnum)` carries exactly the six specified
  values; `AdmissionRowDecodeError(ValueError)` exposes `code` and a
  `scope_key` that is nulled unless it validates as lowercase hex64;
  `decode_admission_record(row, *, header)` re-derives the header from
  the row and rejects disagreement as `invalid_header` with suppressed
  chains.
- All ten prospective tests named by the issue exist verbatim in
  `packages/maistro-core/tests/tasks/test_admission_codec.py` (40 tests
  in the file; 70 with the runs identity file).
- Focused: 201 passed 3 skipped (pure); with
  `MAISTRO_REQUIRE_PG_LEGS=1` on fresh disposable PG 18.6 DB
  `maistro_1893_r7` (container `auto-1893-pg`, port 15498) migrated
  through the real chain 001→062 (`alembic upgrade head`, version row
  `062`): **204 passed, 0 skipped**.
- Live `ck_task_idempotency_v2_identity` probes via the production
  encoder against that DB: production pair INSERT accepted
  (task_id=receipt_id, run_id bound); UPDATE to task_id != receipt_id,
  task_id NULL, run_id NULL, and acknowledged-without-pair each raised
  `CheckViolationError`; probe rows deleted, residue 0.
- mypy CI-exact: `uv run mypy <10 package srcs>` → "Success: no issues
  found in 1052 source files"; `uv run mypy --strict
  packages/maistro-core/src` after `uv sync --locked --all-extras` (the
  quality.yml env) → "Success: no issues found in 784 source files".
  The 5 import-not-found errors seen without `--all-extras` are a local
  env artifact in files this branch never touched
  (`cli/_builders_tui.py`, `cli/_install.py`).
- ruff check "All checks passed!"; ruff format --check "3277 files
  already formatted".

## exact-debt-ledger — residual unchanged and external

- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact arguments): 1323 reviewed
  identities → 1323 findings, exit 0 — **0 unbanked identities**, so
  this round's vulture-ledger amendment allowance has nothing to act
  on.
- `check-shipped-surface-truth.py` → complete; `check-reachability.py`
  → 171 unreachable banked, exit 0; `check-reachability-dispositions.py`
  → 50 groups cover all 171, exit 0; `check-convergence-matrix.py` →
  OK (52 subsystems, 171 attributed).
- `RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py` fails
  exactly as before and **only** on the two admission modules:
  `check-reachability-provenance.py` and
  `check-reachability-dispositions-provenance.py` each name
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
  as NEW unreachable modules/dispositions absent from the trusted base
  and not previously authorized. `origin/develop` re-fetched this round:
  still `435dc1937e04`, still the merge base (0 commits behind), still 0
  admission authorization rows. This is the documented two-merge rule
  (`ratchet_provenance.load_authorizations` reads the grant from the
  merge base): the reachability authorization for the two unwired
  admission modules must land on develop first, then develop merges into
  `auto-1893`. The issue forbids the alternatives in-branch ("no
  baseline/grant/gate modifications to make an unwired slice green"; no
  production activation authorized), and the in-branch baseline/
  disposition rows are the honest disclosure the candidate gates
  require — they do not and cannot turn the provenance gate green.

## Inventory

No tests added or removed this round: `inventory-delta` is 0
(`packages/maistro-core/tests` unchanged at 16466 collected node IDs;
`scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
ok this round via the driver check log).
