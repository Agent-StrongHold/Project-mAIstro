---
inventory-delta:
  tests/: +3
---
# 2432-mutation-trigger-scripts-tooling

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

## What moved

Three tests in `tests/test_mutation_targets.py`
(`TestScriptsToolingSurfaceIsReachable`), pinning the mutation workflow's
coverage of the `scripts/` tooling surface:

- `test_the_scripts_tooling_subtree_actually_exists` — the subtree the new
  trigger names is real, mirroring the existing policy-subtree test.
- `test_every_scripts_tooling_change_is_in_the_workflow_scope` —
  `.github/workflows/mutation.yml`'s `pull_request` paths must keep covering
  `scripts/**/*.py`. The property, not the example: any future trigger-list
  edit that drops the subtree recreates the hang on the next gate-script PR.
- `test_scripts_scope_stays_zero_overlap_by_construction` — the changed-file
  pathspec stays `-- packages`, so the added trigger produces evidence, not
  mutation coverage; a widening of the pathspec would silently change gate
  semantics and this pin fails when that happens.

## Why they exist

PR #2432 (a frontend lockfile bump plus a `scripts/js_dependency_gate.py`
change) never triggered the mutation workflow: no trigger path matches
`scripts/*.py`, so the required-set row "Mutation gate (changed critical
lines)" had no check-run on the candidate head and the `gates-ran` publisher
stayed PENDING forever ("Required execution evidence is still arriving"),
blocking merge-queue admission. Reproduced locally on head 632d5dbaa6 with
the CI-exact evaluator (`check-gates-ran.py --require-complete --base-branch
develop --event-name pull_request --changed-files <measured envelope>`):
exit 2, `not present yet (1): Mutation gate (changed critical lines)` out of
74 required checks — the same documented failure mode #2120 fixed for
`quality/image-pins.json` and #2371 for grant ledgers and inventory notes.

The repair adds the `scripts/**/*.py` path class to the mutation workflow's
trigger (every mutation-critical source lives under `packages/`, and the
job's diff pathspec stays `-- packages`, so scripts-only PRs resolve to real
zero-overlap evidence). With a simulated completed mutation check-run, the
CI-exact evaluator returns `ok: all 74 required check(s) ran on this head`,
exit 0 — the verdict that lets `gates-ran` go green and admits the PR to the
merge queue.

## Validation evidence

- `uv run pytest tests/test_mutation_targets.py -q`: 38 passed (35 + 3 new).
- `uv run pytest tests/test_check_gates_ran.py tests/test_check_required_checks.py
  tests/test_gates_ran_merge_group_scope.py tests/test_gates_ran_publisher_contract.py
  tests/test_mutation_critical.py -q`: 192 passed.
- `python3 scripts/check-required-checks.py`: ok — 79 PR checks match
  `docs/ci/REQUIRED-CHECKS.md`; the mutation row's "Runs on" classification
  is unchanged (`paths`).
- actionlint 1.7.7 with shellcheck 0.10 over all workflows: clean.
- `scripts/check-uv-setup.py`, `check-workflow-write-safety.py`,
  `check-branch-protection.py`, `check-install-functions.py`: ok.
- Full-suite collection for this delta: 21 suites, 35,829 node IDs, only
  `tests/` moved (6126 → 6129, exactly the three new tests).
