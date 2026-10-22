---
inventory-delta:
  packages/maistro-core/tests: +4
---

# 1334-legacy-evidence-migration

Regression coverage for #1334: `DurableRunExecutionStore.transition_node_run`
skipped the canonical write whenever the canonical row already held the
target status, silently dropping the `accepted_outcome` a COMPLETED→COMPLETED
legacy migration was trying to install — from the canonical row and (via the
following `_replace_node_run`) from the durable projection too.

All four cases live in
`packages/maistro-core/tests/graph/durable_runs/test_canonical_execution_store.py`,
on the canonical-backed adapter (`InMemoryRunStore` wired as `run_store`):

- `test_reconciling_a_legacy_completed_node_run_installs_evidence_in_both_stores`:
  the production path — `AttemptLifecycleReconciler.reconcile` through the
  adapter (`attempt_executor._reconcile_orphaned_attempts` wiring) against a
  pre-acceptance COMPLETED NodeRun; asserts the outcome lands in canonical,
  returned row, and projection, with lifecycle timestamps preserved.
- `test_a_same_status_transition_attaching_legacy_evidence_reaches_the_store`:
  the bare delegated transition (no reconciler) carries the outcome to the
  store that owns the row.
- `test_a_same_status_transition_with_already_attached_evidence_stays_a_no_op`:
  pins the contract the fix must not break — a replay whose outcome differs
  only in `accepted_at` stays a no-op (the store's validator refuses
  completed→completed outright), because the acceptance clock is not evidence.
- `test_a_same_status_transition_with_conflicting_evidence_surfaces_the_disagreement`:
  an outcome that disagrees with the recorded result raises
  `InvalidLifecycleTransition` from the store's migration validator and
  leaves both stores unwritten.

The first two and the fourth fail against the pre-fix adapter; the third
passes on both sides by design (it guards preserved behavior).
