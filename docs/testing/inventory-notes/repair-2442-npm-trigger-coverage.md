---
inventory-delta:
  tests/: +1
---

# Repair #2442: npm dependency metadata is trigger-covered for the mutation producer

The `gates-ran` commit status on PR #2442's head `251b4e2e71eb` (react
19.2.0 → 19.3.1 in `packages/hive-conductor/tests/e2e`) was stuck
`pending` ("Required execution evidence is still arriving"), which the
merge-queue precondition reports as "commit status not successful".
First-party measurement with the CI-exact evaluator at that head showed
**73/74** required checks present and green; the sole absent row was
`Mutation gate (changed critical lines)`. The PR's changed-file envelope
is exactly `packages/hive-conductor/tests/e2e/{package.json,package-lock.json}`,
none of which matched `mutation.yml`'s `pull_request.paths` filter, so the
producer never fired — the same documented failure mode previously repaired
for five other surface classes (#2120, #2371, #2432, #2345, #2450). The
evaluator deliberately refuses to excuse such absence (#2434 replay pin),
so the repair is trigger coverage, not evaluator leniency.

## Change

- `.github/workflows/mutation.yml`: added `packages/**/package.json` and
  `packages/**/package-lock.json` to the PR trigger paths, with the
  incident rationale inline. Zero overlap is by construction (every entry
  in `quality/mutation-critical-files.json` is a `.py` source under
  `packages/`), so npm-bump PRs get real "No mutation-critical file
  changed" evidence and the job still fails closed on any critical change.
- `tests/test_check_required_checks.py`: `TestPathsFilters.SHIPPED`
  updated in lockstep (the constant pins the shipped filter verbatim), and
  one new test,
  `test_npm_dependency_metadata_is_inside_the_mutation_producer_trigger`,
  pins the class under GitHub's paths-filter match semantics: the exact
  #2442 envelope plus the repo's other manifest/lockfile locations must
  match; a critical `.py` source must match the filter but never the npm
  entries; a sibling test asset must not match at all.

## Executed evidence

- `uv run pytest tests/test_check_required_checks.py
  tests/test_check_gates_ran.py tests/test_gates_ran_publisher_contract.py
  tests/test_check_branch_protection.py -q` — **204 passed** (includes the
  new test).
- Regression pin proven the other way: the matcher helper driven with the
  pre-fix filter (npm globs removed) does **not** match
  `packages/hive-conductor/tests/e2e/package.json`, while the post-fix
  filter does — the new test fails against the tree the repair replaces.
- CI-exact evaluator replay of the captured head evidence
  (`check-gates-ran.py --require-complete --base-branch develop
  --event-name pull_request --changed-files <measured envelope>`):
  pre-repair = PENDING with `not present yet (1): Mutation gate (changed
  critical lines)`; the identical 80-run shape with the row present
  returns `ok` (exit 0), which is exactly the post-repair head shape once
  the producer fires.

No evaluator, gate, or ledger logic was weakened: `check-gates-ran.py`,
`check-required-checks.py`, and `quality/*.json` are untouched.
