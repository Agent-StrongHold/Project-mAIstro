---
inventory-delta:
  formal/: +1
---

# 880 M8-A: make the execution lifecycle state machine runnable

This change resolves the pytest collection blocker for leaf #881: the
`ExecutionLifecycleMachine` Hypothesis state machine is now exposed as
`TestExecutionLifecycleMachine = ExecutionLifecycleMachine.TestCase` (the
pattern the other formal models use), so it actually runs in the
formal-conformance leg. Each step now calls the production
`transition_run` helper from `maistro.runs.lifecycle` instead of mirroring
the status by hand, and the invariants check the table's domain. The
research note and assurance-matrix row for #881 are updated from WATCH to
INCUBATE to reflect the runnable evidence.
