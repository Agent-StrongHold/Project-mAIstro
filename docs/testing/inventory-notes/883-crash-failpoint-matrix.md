---
inventory-delta:
  packages/maistro-core/tests: +22
---

# #883 deterministic crash/failpoint matrix (M8-A3 prototype)

Bounded research prototype: a test-tree failpoint lab plus deterministic
operation x failpoint x recovery matrices over the two boundaries the issue
names -- the task execution spine (`packages/maistro-core/src/maistro/tasks/execution.py`)
and the external-effect Invocation boundary
(`packages/maistro-core/src/maistro/capabilities/invocation.py`).

New files, all under `packages/maistro-core/tests/failpoints/`:

- `_failpoints.py` -- the reusable machinery: `CrashPoint` (transparent store
  wrapper raising a `BaseException` crash at one named write, before or after
  it commits, armed explicitly, firing at most once), `StatusJournal`
  (whole-timeline terminal-regression oracle), `EffectLedger` (the remote
  system's ground truth for duplicate-effect checks), `CrashSimulated`.
- `test_task_execution_failpoint_matrix.py` -- 10 cells: claim (x2), work loss
  (x2 crash points x 2 recovery strategies), attempt terminal commit (x2), Run
  terminal commit (x2), each asserting the canonical recovery halves settle or
  resume the Run, the receipt agrees where the tier can carry one, and no
  terminal state regresses.
- `test_invocation_failpoint_matrix.py` -- 7 cells over admission, running
  persistence, and terminal commit seams: at most one physical provider call
  per logical effect in every combination, crash-before vs crash-after-effect
  distinguishable through discovery + `dispatch_active`, replay without a
  second call after settlement.
- `test_failpoint_machinery_inert.py` -- 5 guards: disarmed pass-through,
  fire-once, predicate rejection does not spend the failpoint, regression
  oracle self-test, and a source scan asserting no `packages/*/src` module
  references the lab (it cannot ship enabled because it cannot ship).

Net: +22 collected node IDs on `packages/maistro-core/tests`. Experiment
record and INCUBATE recommendation:
`docs/testing/failpoint-matrix-evidence.md`.
