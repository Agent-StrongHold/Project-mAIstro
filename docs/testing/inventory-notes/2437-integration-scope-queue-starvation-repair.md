---
inventory-delta:
  tests/: +0
---

# #2437 integration-scope: evidence window re-measured for queue starvation (+0 node/pytest count)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

CI-repair round for #2437's `integration-scope` blocker (workflow run
44748434713, job/check-run 136329705554, head caaabe8dc39b). The aggregator
failed with "timed out waiting for required specialized CI evidence" while
**every required specialized producer later concluded success on the same
SHA**: scope resolution was correct (locally reproduced — the candidate
touches only `packages/hive-conductor/frontend/package{,-lock.json}`, so the
classifier requires exactly docker-build, hive-conductor-e2e,
hive-conductor-e2e-ui, wheel-imports), but those four producers were created
~14:36Z and sat queued ~124 minutes before the first started at 16:40Z. The
240×30 s (120-minute) poll budget expired at ~16:35Z and the aggregator
failed at 16:38:18Z; the required evidence landed 16:40:50–16:59:24Z, 2–21
minutes too late. Same failure class as the #41/#869 raises already
documented in the workflow: the window must cover queue starvation, not just
execution time.

Repair: widen the evidence window to 360×30 s (180 minutes) inside a
190-minute job timeout (attempt cadence and ~120 check-list requests/hour
unchanged). This only extends patience for *pending* evidence; failure
semantics are untouched — a required check's non-success conclusion still
fails the aggregator immediately, and budget exhaustion still fails closed
with the same verdict.

Test deltas, counts unchanged:

- `tests/ci/integration-scope.test.cjs` (node, not part of the pytest
  inventory): the workflow-shape pin moves 125→190 / 240→360 and its comment
  records the #2437 measurement.
- `tests/test_buildx_build_retry.py::test_specialized_producer_and_aggregator_budgets_are_coherent`:
  the measured queue-lag floor moves from #869's 35 minutes to the larger
  #2437 measurement (125 minutes), so the coherence invariant now demands
  evidence ≥ 125 + 45 = 170 minutes. That strengthened floor **fails** the
  pre-repair workflow (240×30 s = 120 < 170) and passes the repaired one
  (180 ≥ 170, 190 > 180) — the regression the rename names is the budget
  the run exhausted.

`tests` delta is **+0**: no test was added or removed; two existing pins were
re-measured and strengthened.

Known cost of touching a classifier-global file: any edit to
`.github/workflows/integration-scope.yml` puts the path in
`_GLOBAL` (`scripts/ci_merge_group_scope.py`), so this PR's scope fails
closed to every specialized leg — postgres, object storage, durable-events
and strike-ladder will now *run* (not skip) on this candidate and must
conclude success. That is the designed drift cost (#1351), not a gate
weakening.
