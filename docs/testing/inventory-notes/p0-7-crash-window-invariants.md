---
inventory-delta:
  packages/maistro-core/tests: +6
---
# p0-7-crash-window-invariants

Six new tests in `packages/maistro-core/tests/runs/test_crash_window_invariants.py`
(P0.7 of the Workspace cutover plan, AC-P7, owner #804). Each of five tests kills the
process at one two-write seam on the execution spine, then runs one tick of the
recovery cadence Hive schedules (the Container's abandoned-Attempt, stranded-chat and
parked-Run halves, then the queued and due durable-Graph halves). It asserts that no
Run is left RUNNING with no live Attempt. The sixth test checks that every
`KNOWN_GAPS` entry names a real window.

Four windows are still open and listed in `KNOWN_GAPS`, so their tests assert that the
Run is still stranded after one tick:

- Run settlement lost after the last NodeRun commits.
- The Attempt's completion write lands, then reconciliation never runs.
- The next frontier's NodeRun is minted after the checkpoint cleared `resume_at`.
- The continuation is written terminal before its canonical mirror. This one settles
  on a later tick, once the quiet period has passed.

One window is already closed: a completion write lost before it commits leaves a
leased RUNNING Attempt, and the lease sweep parks the Run.
