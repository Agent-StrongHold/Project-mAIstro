---
inventory-delta:
  packages/maistro-core/tests: +2
---
# P4a: PG recovered-disposition missing-NodeRun branch arcs

Two stand-in node IDs in
`packages/maistro-core/tests/runs/test_pg_recovered_attempt_disposition.py`
cover `_locked_recovered_disposition_tree` refusal branches that diff-coverage
flagged below the 80% floor:

- `test_missing_node_run_row_refuses_disposition` — unlocked lineage read raises
  `NodeRunNotFound` when the Attempt's NodeRun row is gone.
- `test_locked_set_missing_candidate_refuses_disposition` — FOR UPDATE set omits
  the candidate (row rebound to another run); disposition refuses with
  `NodeRunNotFound`.
