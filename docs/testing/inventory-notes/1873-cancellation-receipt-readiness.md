---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/maistro-server/tests: +8
---

# #1873 cancellation receipt readiness

Refs #1339, #1690, #91, #849. This is a bounded refresh of PR #1873's
same-replica cancellation projection onto develop `ab8b3737`. It includes the
original production patch, two bounded correctness repairs and fourteen
collected cases; no test is removed
and no coverage floor or shared inventory baseline changes.

The canonical cancellation service owns the Run and physical cancellation.
When this process already holds the task receipt, the Run API asks the queue
to reconcile its state and then projects canonical timestamps and outcome.
An already-cancelled Run accepts the redundant task transition; that is why
the explicit settlement must overwrite the ordinary path's wall-clock finish
time. A completed canonical winner remains completed through the refusal
reconciliation path. The queue, rather than the route, owns gauge accounting.

Independent review found and reproduced two additional gaps in the original
patch. The route now verifies the local receipt's reciprocal `run_id` before
any queue transition, and settlement independently rejects a different Run.
The canonical empty result also clears an obsolete local result rather than
leaving stale files/error visible. These preserve existing Run authority.

## Added evidence

- Core: three real Run-store/lifecycle cases (completed, failed, cancelled)
  check canonical start/finish times, result/error projection, waiter
  notification, ordered persistence snapshots and repeated settlement without
  a second active-gauge decrement. The fake session measures scheduled writes;
  it is not a PostgreSQL durability proof.
- Core: missing and non-terminal local receipts are unchanged by settlement,
  with no fabricated receipt and no new persistence write.
- Core: a terminal receipt rejects settlement from a different Run; canonical
  empty outcomes also clear stale local results in the ordered write snapshot.
- Server: four cases cover non-task provenance, absent task ID, empty task ID
  and non-string task ID. The non-task case deliberately names an existing
  task receipt to prove correlation alone does not confer ownership.
- Server: a real task Attempt that completed before cancellation remains the
  canonical winner and repairs its queued local receipt to completed.
- Server: a second empty queue can cancel the canonical Run, but does not gain
  a receipt or update the accepting queue. This explicitly exposes the scope
  boundary rather than treating a missing local receipt as convergence.
- Server: same-source provenance pointing at another principal's task cannot
  change that other canonical Run, receipt or active gauge. This deliberately
  injects inconsistent provenance through the store; it is not evidence of an
  externally reachable provenance-forging API.
- Server: an already-cancelled canonical Run with no result/error clears the
  local stale result, including the response from `GET /tasks/{task_id}`.
- Existing server cases now also check cancellation result/timestamp parity,
  repeated cancellation without a gauge decrement, and unknown/foreign/no-store
  cancellation responses without changing their collected counts.

## Remaining acceptance boundary

This patch is process-local. It does not route cancellation to another
replica's queue, refresh another process's cached receipt, or make receipts
readable from a different replica. The accepting replica can still retain a
queued receipt and active gauge after cancellation is handled elsewhere.
The two-queue in-memory test is not a two-process shared-PostgreSQL topology,
restart/failover, or durable-write-drain acceptance proof.

Those shared-visibility and convergence obligations remain in #1690 and the
#91/#849 durable admission/receipt work. A single-replica or sticky-routing
deployment is only an explicit interim limitation; this change does not
establish that production uses either topology. It does not close #1339's
cross-replica concern, authorize a cutover, or alter #1845's admission generation
work. Keep the corrective PR draft until current-head CI and review pass and
the owner accepts this bounded disposition.

## Executed validation after the review corrections

Python 3.12.14; imports verified to resolve from this candidate checkout.

- `pytest packages/maistro-core/tests/test_queue.py
  packages/maistro-core/tests/tasks packages/maistro-server/tests -q
  --cov=maistro.tasks.queue --cov=maistro_server.api.runs --cov-branch`:
  **1,099 passed, 26 skipped**. This is the task/queue and full server slice,
  not the complete monorepo test suite.
- Both changed test files run together after negative controls:
  **35 passed**, also independently reproduced during re-review. Core fitness
  suite before the two review corrections: **23 passed**.
- The repository's `check-diff-coverage.py` against `ab8b3737`: queue.py
  **11/11 changed executable lines (100%), 5/6 changed arcs (83.3%)**;
  runs.py **12/12 lines and 6/6 arcs (100%)**. Floors stay **90%/80%**.
- The configured seven-package strict mypy command: **899 source files,
  no issues**. Whole-tree Ruff lint and format checks pass.
- Radon, Vulture, execution-lifecycle classification, reachability scan, and
  duplicate-test gates pass without ledger changes.
- Suite inventory passes: core **16,366**, server **573**. The only inventory
  edits are this note's +6 and +8 deltas.
- Before the review corrections, controlled negative runs verified the
  original repair's assertions: restoring the pre-fix route leaves the receipt
  queued; removing canonical settlement produces a mismatched completion
  timestamp; ignoring admission source changes an unrelated local receipt.
  Candidate source was restored before subsequent validation.

Independent re-review clears the bounded diff. Hosted current-head CI and the
owner's acceptance of the bounded disposition are still required. No real
multi-process PostgreSQL or production deployment claim follows from these
local results.

## Independent-review corrections

All three added review regressions failed against the uncorrected original
production patch: cross-linked provenance changed another canonical Run;
settlement accepted a different Run; and canonical cancellation with an empty
outcome left stale files in the task receipt. After the reciprocal identity
guards and unconditional canonical result assignment, the focused files pass
**35 tests**, including an unchanged foreign Run, receipt and gauge. The
broader corrected-candidate results are recorded above.
