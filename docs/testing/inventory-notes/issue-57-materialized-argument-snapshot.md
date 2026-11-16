---
inventory-delta:
  packages/maistro-core/tests: +2
---
# Issue #57: keep admitted tool input stable across awaits

Two deterministic asynchronous regressions exercise the real
`GovernedToolExecutor.execute` through the canonical Binding/Invocation service.
A caller changes both a top-level string and a nested array to schema-invalid
values while execution pauses at Binding lookup or provider entry. Neither
mutation may reach the provider or detach the executed input from the persisted
request, effect key, materialized-argument evidence and digest. The nested case
requires a deep snapshot rather than a shallow dictionary copy.

The tests synchronize with events (no timing/scheduling sleeps); the timeout is
only a deadlock guard. Existing schema-denial and prediction-mismatch tests
remain the negative controls. This does not grant authority, add an executor or
change Invocation lifecycle ownership.

Red/green results and remaining issue-level acceptance limitations are recorded
in `.cursor/context/repair-57-cf70231d.md`.
