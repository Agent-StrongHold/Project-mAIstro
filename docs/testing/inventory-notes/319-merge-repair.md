---
inventory-delta:
  quality/branch-independence.json: +2 surfaces
  scripts/check-ratchet-provenance.py: merge resolution only
---
# Issue 319 merge repair (auto-319)

Repair of the #319 branch against current develop (merge of ba2f1f077).

- `scripts/check-ratchet-provenance.py`: develop renamed the module constant
  `TRUSTED_ADAPTERS` to `DELEGATED_ADAPTERS`. The merge keeps the branch's
  trusted-base policy parameterization and adopts the new constant name, and
  the first-landing fallback that parses the allow maps out of the *base*
  inventory source now accepts either historical constant name
  (`_source_mapping_any`), so the oracle survives bases on both sides of the
  rename. Verified post-merge: the full gate resolves from base ba2f1f077 and
  all delegated adapters pass.
- `quality/branch-independence.json`: the two ledgers introduced by this
  branch (`quality/ratchet-provenance.json`,
  `quality/workflow-ratchet-baseline.json`) were unclassified repository state,
  failing `tests/test_branch_independence_repository.py`. Both are classified
  `base_derived` with reasons naming the trusted-base checker that owns each
  comparison; neither participates in the frozen legacy set, so the candidate
  cannot expand it via this edit.
- The workflow floors recorded in `quality/workflow-ratchet-baseline.json`
  match the legacy inline floors at the post-merge trusted base ba2f1f077
  (coverage 87, diff lines 90 / branches 80, xenon 77, pyright 21,
  interrogate 38/45/63/46), so the first-migration legacy parse still lands on
  the same floors after the merge.
- Reconciliation recorded for prior finding "`ratchet_provenance.py:309-311`
  returns a worktree baseline without a base": the worktree read is the
  documented local-development affordance (module docstring; every CI workflow
  names `RATCHET_BASE_REV` or GitHub event metadata, and named-but-unusable
  bases raise instead of downgrading). Tests pin the labeling
  (`test_no_base_anywhere_reads_the_worktree_and_says_so`,
  `test_a_worktree_verdict_says_it_is_not_a_monotonicity_check`) and the
  fail-closed CI states (`test_a_named_base_that_cannot_be_resolved_raises`,
  `test_an_unreachable_base_raises_rather_than_reading_the_worktree`,
  `test_a_clean_checkout_sitting_on_its_own_base_is_refused`).
- Validation executed in this worktree: `uv run python
  scripts/check-ratchet-provenance.py` (inventory + delegated gates, base
  ba2f1f077), `scripts/check-branch-independence.py`,
  `scripts/check-required-checks.py`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest tests/` (3414 passed; the
  only failure, `test_m1_542_policy_coverage.py::
  test_model_egress_main_covers_missing_success_and_unauthorized_paths`, is
  pre-existing at ba2f1f077 — isolated-run import fragility on develop,
  passes with normal suite ordering), and the targeted ratchet battery
  (207 passed). Workflow checkers were executed without artifacts and failed
  closed as designed ("No data to report", "failed without a measurement",
  "no readable JSON measurement").
