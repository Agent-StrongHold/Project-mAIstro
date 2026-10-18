---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-server/tests: +2
---
# auto-849-repair-gates

#849 repair round on branch `auto-849` (starting head `9e2b8bdb1b60`): close
the two diff-coverage gate failures the L849 verification records name, with
tests — no production behavior change beyond the container refactor below.

Four additions, no removals and no parametrization changes:

- `tests/tasks/test_workspace_routing.py` (+2): the workspace-routed
  `WorkspaceRoutingAdmitter.lookup_run` read — a submitted Run comes back
  through the default admitter's store unchanged, and an unknown run_id
  reads as None. Covers the `lookup_run` delegation the receipt
  reconciliation leans on.
- `packages/maistro-server/tests/test_queue_singleton_drain.py` (new, +2): the shutdown
  drain of the task-queue singleton — `_drain_queue_singleton` awaits
  `drain_persistence` on the shutdown path, and a failing drain is logged
  (`task_receipt_drain_on_shutdown_failed`) rather than raised into
  lifespan teardown, because the canonical Run still holds the truth.

Production refactor in the same round (no test-count effect):
`Container.resume_parked_runs_accounting` is split — the per-Run claim and
disposition moves to `_resume_one_parked`, returning a
`ParkedResumeOutcome` the accounting loop counts. Behavior-identical; both
blocks land at radon rank B so the radon ratchet returns to 67 = 67.
