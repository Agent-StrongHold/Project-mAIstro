---
inventory-delta:
  tests/: +1
---
# CR-1640: mutation trigger must let the required check report

Suite: `tests/`
Delta: +1 collected case (`test_no_pr_workflow_paths_filters_its_required_check_out_of_reporting`
in `tests/test_check_required_checks.py`); one existing case's body rewritten
(`test_every_package_source_is_in_the_workflow_scope` in
`tests/test_mutation_targets.py`) with no node-id change. No tests removed,
renamed, skipped or weakened.

The new case pins the structural invariant whose absence let the deadlock ship:
a `paths:`-filtered `pull_request` trigger on a workflow that emits a required
check detaches the required context from every PR outside the filter — GitHub
creates no check run, so `gates-ran` stays pending and the merge queue reads
the branch as "commit status not successful". The case fails against the
pre-repair workflow (verified against `9ef8d6604:.github/workflows/mutation.yml`,
which it flags as an offender) and passes on the repaired trigger. The rewritten
`tests/test_mutation_targets.py` case pins the same property from the mutation
side: the trigger stays unfiltered (a superset of any path list) while the job
keeps diffing `-- packages`.

No baseline or workflow inventory change beyond the reviewed trigger widening
recorded in `docs/ci/REQUIRED-CHECKS.md` and `quality/workflow-inventory.json`.
