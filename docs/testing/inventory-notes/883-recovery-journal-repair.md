---
inventory-delta:
  packages/maistro-core/tests: +1
---
# #883 repair: recovery writes reach the journaling oracle

Repairs the four Codex P2 findings on the #883 failpoint-matrix prototype
(PR #2056); this note records the suite-count movement the repair adds.

The one new test is
`test_failpoint_machinery_inert.py::test_a_wrapped_store_keeps_its_claim_protocol`:
it pins the boundary the other repair cells depend on. Runtime-checkable
protocols resolve members with `inspect.getattr_static`, which `__getattr__`
never answers, so `CrashPoint` forwards `claim` through an explicit method --
without it a wrapped store fails the `EffectClaimStore` check and
`InvocationExecutionService._admit_effect` silently drops to its `create`
fallback, crashing the wrong write at the admission seam.

The repair also rewires the existing cells without changing their count:

- `_recovery_tick` keeps the lifecycle reconciler on the journaled store
  instead of unwrapping it, so the terminal/parked transitions recovery lands
  reach the whole-timeline no-regression oracle (previously the oracle was
  blind across the recovery phase).
- The machinery-inert source scan parses imports (AST) instead of substring-
  matching prose, so a production comment mentioning "failpoint" is no longer
  a false boundary violation.
- `test_run_terminal_commit_seam` now runs against a durable receipt tier and
  asserts the #849 receipt reconciliation actually projected the terminal Run
  onto the durable row -- previously the recovered queue was discarded and the
  named product surface went unasserted.
