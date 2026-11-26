---
inventory-delta:
  tests/: +4
---

# CI #2485: npm dependency-bump PR surfaces must trigger the Mutation gate

Four structural tests pin the `pull_request.paths` widening in
`.github/workflows/mutation.yml` that repairs the merge-queue admission
failure "commit status not successful" on PR #2485 (@eslint/js 9.39.5 →
10.0.1 in `packages/hive-conductor/frontend`, head d329b1a07c).

## Failure mode, measured not guessed

`check-gates-ran.py --require-complete --base-branch develop --event-name
pull_request --changed-files <measured 2-file envelope>` against the live
check-run payload captured at head d329b1a07c exits 2 (PENDING) with exactly
one absent required row: "Mutation gate (changed critical lines)". All 73
other required checks in the 74-check execution-evidence set were present,
successful, or legitimately skipped —
including "Container scan + SBOM + cosign" and "test", the rows an earlier
round left red — so no later publisher run could ever flip the verdict: the
PR's envelope (`packages/hive-conductor/frontend/package.json`,
`packages/hive-conductor/frontend/package-lock.json`) matched no `paths:`
pattern, GitHub never created the Mutation check-run, and the evaluator can
only excuse a check that is *present* and skipped. This is the same
producer-absence failure mode repaired five times before (#2120 image pins,
#2371 grant ledgers + inventory notes, #2432 gate scripts, #2345 dev-tool
requirements, #2450 uv.lock/pyproject.toml/.trivyignore.yaml); #2485 is the
first npm-bump PR to hit it.

## What the tests pin

`TestJsDependencyBumpPrSurfacesStillTrigger` in `tests/test_mutation_targets.py`:

- The two new trigger entries exist in the parsed workflow
  (`packages/**/package.json`, `packages/**/package-lock.json`) and match
  exactly the envelope classes of #2485 — one test per surface, so a future
  revert that drops either entry fails a named test.
- The surfaces exist on disk (a trigger for a deleted path would be dead
  text).
- Zero-overlap is structural: every entry in
  `quality/mutation-critical-files.json` is a `.py` source under `packages/`,
  and the job's changed-file pathspec stays `-- packages`, so npm
  manifest/lockfile diffs always resolve to "No mutation-critical file
  changed; nothing to mutate." The widened gate gains execution evidence
  without changing what it mutates; it still fails closed when a critical
  `.py` changes.

`tests/test_check_required_checks.py` `TestPathsFilters.SHIPPED` is updated
under review as its docstring requires: the map the gates-ran evaluator
discovers now carries the two npm globs.

End-to-end proof at the edited tree: appending a synthetic successful
"Mutation gate (changed critical lines)" check-run to the captured payload
flips the same CI-exact evaluator invocation from PENDING (rc=2) to
`ok: all 74 required check(s) ran on this head` (rc=0) — i.e. the first
post-push Mutation run publishes gates-ran success and unblocks the merge
queue.

## Validation evidence (this repair round, head d329b1a07c)

- CI-exact evaluator against the captured head payload:
  `python3 scripts/check-gates-ran.py --check-runs <captured>
  --require-complete --base-branch develop --event-name pull_request
  --changed-files <measured envelope>` → exit 2, `not present yet (1):
  Mutation gate (changed critical lines)` out of 74 required checks; with
  the synthetic completed mutation check-run → exit 0, all 74 ran.
- `uv run python scripts/mutation_critical.py --changed-from` over exactly
  the #2485 envelope (package.json + package-lock.json) → exit 0, "no
  mutation-critical files in the changed set" (real zero-overlap evidence);
  `--validate` → ok, 8 sources across 7 domains.
- `uv run pytest tests/test_mutation_targets.py
  tests/test_check_required_checks.py -q`: 122 passed.
- `uv run pytest tests/test_check_gates_ran.py
  tests/test_gates_ran_merge_group_scope.py
  tests/test_gates_ran_publisher_contract.py tests/test_pr_scope_policy_parity.py
  -q`: 106 passed.
- Regression proof for the new tests: `_paths_match` over the pre-repair
  paths list (git show HEAD) does not trigger the #2485 envelope; the new
  list is a pure addition (all 13 prior entries retained) and the README.md
  negative control still does not trigger.
- actionlint 1.7.7 with shellcheck over all workflows: clean.
- `python3 scripts/check-required-checks.py`: ok — 79 PR checks match
  `docs/ci/REQUIRED-CHECKS.md`; the mutation row's classification is
  unchanged.
- `uv run python scripts/check-suite-inventory.py`: ok — 21 suites match;
  `tests/` = baseline + accumulated deltas including this note's `+4`.
- `scripts/check-workflow-inventory.py`, `check-workflow-write-safety.py`,
  `check-uv-setup.py`: ok (33 workflows dispositioned).
- `uv run ruff check .` on touched trees and `uv run ruff format --check
  tests/`: clean.
