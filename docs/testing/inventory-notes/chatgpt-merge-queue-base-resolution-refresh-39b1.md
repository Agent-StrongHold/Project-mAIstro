---
inventory-delta:
  tests/: +6
---
# chatgpt-merge-queue-base-resolution-refresh-39b1

Closes the diff-coverage gap this branch's own changes to
`scripts/check-ac-state.py` and `scripts/ci_merge_group_scope.py`
exposed: 2 new node IDs in `tests/test_ac_state_merge_guard.py`
(`_actual_base_revision`'s delegation to the shared resolver, and
`main()`'s `BaseRevisionError` handling) and 4 in
`tests/test_ci_merge_group_scope.py` (the `durable_events` and
`strike_ladder` classification branches, plus the CLI entrypoint's
plain and `--json` output). No existing test moved or was removed.
