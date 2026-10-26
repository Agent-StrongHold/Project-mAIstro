---
inventory-delta:
  tests/: +43
---

# Recover reusable check discovery from #1357

Refs #1357 and #160. This is a prerequisite slice, not completion of the
CI-efficiency audit or the coverage work in #1605.

## Preservation provenance

The caller/callee check-name composition is adapted from `df7c657a` on the
historical #1357 branch. The five fail-closed regression scenarios introduced
by `1df6d670` are preserved as behavioral tests using valid repository-root
workflow paths: unresolved input, external workflow, missing callee, empty
callee, and unresolvable callee name. The old branch and its rollback are not
merged or rewritten. The original workflow split, PostgreSQL migration wiring,
Vulture trigger migration and broader check-policy rollout remain separate.

The current source baseline is `develop@8b494ea3f369704414561c5c26fa9a6ccd73e362`.
The fetched script was checked against Git blob
`7d791eb5bfe14bfff2a25b25a1ce0b163beb21b4` before editing.

## Supported contract

Single-level, same-revision local reusable callers emit literal caller/callee
names. Declared string inputs and literal defaults can supply callee names.
Missing or unsupported evidence is a ContractError, not an invented name.
The adaptation additionally checks callable workflow structure, path containment,
nonempty names, duplicate callee names and input-map shape. Unsupported nested,
matrix or conditional callee jobs are refused explicitly. Existing direct-job
and direct-matrix handling is unchanged. The caller remains responsible for
merge_group coverage and PR-base scope.

No workflow, trigger, job, permission, required context, baseline or service
profile changes here. This parser alone does not authorize switching production
jobs to reusable workflows: workflow-write safety, reachability and every other
policy consumer must support the selected topology before that migration.

## Executed evidence

43 focused tests pass under Python 3.13.5 with PyYAML 6.0.3 and pytest 9.0.2.
They drive the real collect() entry point over temporary workflow trees and the
real merge_group_gaps() decision over temporary protection declarations.
Coverage of all four added helper functions has no missing statements or branch
arcs in this focused run. This is not a claim of whole-script or whole-repository
100% coverage. All pre-existing function/class ASTs except collect() are
unchanged. No test count was removed to make room for these cases.

Local environment does not have the complete locked repository or Ruff. Full
repository CI, format/lint, suite inventory and independent review are still
required on the published candidate. No compute or wall-time saving is claimed
for this prerequisite; runtime deduplication remains the broader audit's goal.

## Re-validation at the develop-sync head (2026-10-26)

Branch state: `ci/1357-reusable-discovery` at merge commit `6a73d1029`
(parents: PR head `abfd7e82b`, develop tip `10f872fa7`). `origin/develop` has
not moved past `10f872fa7`. The rendered `docs/ci/REQUIRED-CHECKS.md` and every
`.github/workflows/` file are byte-identical to `origin/develop`; the diff
surface is still the nine files listed in the PR surfaces, and
`git diff --numstat origin/develop -- quality/` is empty (no ledger rows).

Independently re-executed evidence at that head:

- `uv run ruff check .` and `uv run ruff format --check .`: pass (3559 files).
- Focused suites: 169 passed — 72 in `test_reusable_check_discovery.py`, 34 in
  `test_reusable_discovery_review.py`, 63 in `test_check_required_checks.py`.
  The 106 new tests equal the `inventory-delta` sum above (43+24+16+23).
- `python3 scripts/check-required-checks.py` (ci.yml:1458): ok, 77 PR checks
  match `docs/ci/REQUIRED-CHECKS.md`.
- `scripts/check-suite-inventory.py` (ci.yml:723, project venv): ok, 21 suites,
  `tests/: 6146`.
- `python3 scripts/check-workflow-write-safety.py` (ci.yml:1471): ok, 32
  workflows.
- `python3 scripts/check-branch-protection.py` (ci.yml:1481): ok, 19 develop /
  33 main contexts, every PR check required or explicitly advisory.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: 1248 reviewed identities = 1248 findings, rc 0.
- `scripts/check-merge-markers.py`: ok, no conflict markers in tracked files.
- Diff coverage: the three focused suites under
  `coverage run --branch --source=scripts`, then
  `scripts/check-diff-coverage.py coverage.xml --base origin/develop`: ok —
  1 changed file measured at or above 90% lines / 80% branch arcs; the three
  new test files are exempt as test code.
- Regression reality: in a `/tmp` sandbox pairing `origin/develop`'s
  `scripts/check-required-checks.py` with these 106 new tests, 103 fail and 3
  pass. The recoveries are genuine regressions against the preceding
  implementation, not vacuous fixtures.

Residual: exact-head remote CI has not run (push is outside this worker's
authority). The d1e92738 "Container scan + SBOM + cosign" cancellation was
runner teardown, not code evidence against this slice.

## Re-validation at the recorded head 106886705 (2026-10-26, job 0bd38819)

Head `106886705` differs from `6a73d1029` only by the docs commit recording the
section above; no code, workflow or ledger bytes changed. `origin/develop` is
still `10f872fa7` (merge-base equals it, 0 commits behind). The 9-file surface
is unchanged and matches the PR surfaces. Independently re-executed:

- Driver checks at this exact head: `uv sync --locked --extra dev` ok,
  `uv run ruff check .` ok, `uv run ruff format --check .` ok (3559 files).
- Focused suites: 169 passed (72 + 34 + 63), matching the `inventory-delta`
  sum 43+24+16+23 = 106 new tests (72 + 34 across the two new files).
- Consumer suites: 304 passed across reusable discovery, required checks,
  branch protection, workflow-write safety and both gates-ran suites.
- CI-exact gates: `check-required-checks.py` ok (77 PR checks);
  `check-workflow-write-safety.py` ok (32 workflows); `check-branch-protection.py`
  ok (19 develop / 33 main); `check-suite-inventory.py` ok (21 suites);
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` ok (1248 reviewed = 1248 findings, base 10f872fa7 /
  candidate 106886705); `check-merge-markers.py` ok; `check-release-consistency.py`
  ok (0.9.0 working toward 1.0.0).
- Diff coverage re-measured with the three focused suites under
  `coverage run --branch --source=scripts` and
  `check-diff-coverage.py coverage.xml --base 10f872fa7`: ok, 1 changed file at
  or above 90% lines / 80% branch arcs, 3 test files exempt.
- `.github/` and `docs/ci/REQUIRED-CHECKS.md` byte-identical to `origin/develop`;
  `git diff --numstat origin/develop -- quality/` empty.
- Regression reality re-proven in a `/tmp/reg1609` sandbox pairing
  `origin/develop`'s `scripts/check-required-checks.py` with the two new test
  files: 103 failed, 3 passed. The three passes name behavior develop already
  had (direct-job names, caller merge-group obligation, PyYAML loader
  isolation); every discovered-name, default-resolution, malformed-mapping and
  fail-closed case fails against the preceding script.

Residual unchanged: exact-head remote CI still requires the push; the recorded
d1e92738 cancellations (Container scan/SBOM/cosign, and the downstream
integration-scope failure) were runner-teardown cascades at a superseded head,
not evidence against this slice. Human review/admission remains required:
`scripts/check-required-checks.py` is a trusted CI surface under the
protected-base autonomous-merge policy.
