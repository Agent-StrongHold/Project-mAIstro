---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# Issue #65 Goal inspection repair — dedicated retry/replan provenance test

CI-repair round for #65 (`auto-65`). The verify round left one residual:
retry/replan provenance had no dedicated test — its visibility rode the
child-run/delegation test's assertions on the exposed `parent_run_id`/
`provenance` fields.

The repair adds
`test_retry_of_a_failed_attempt_stays_in_one_history` to
`packages/hive-conductor/backend/tests/test_goal_inspection.py`: a failed
attempt plus a retry Run admitted with parent lineage and an admission-path
provenance key (`retry_of`) must stay in the Goal's ONE history
(`run_count == 2`), carry the lineage and verbatim provenance through the
view, and leave the failed attempt failed and still the Goal's blocker.

One backend test added, none removed; no other suite moved.
