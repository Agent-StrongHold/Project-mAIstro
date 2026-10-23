---
inventory-delta:
  tests/: +12
---

# #860 — malformed soak evidence must fail closed

Adds twelve parametrized cases to
`tests/test_soak_promotion_gates.py::test_malformed_gate_records_cannot_pass_cli`.

The existing evaluator accepted `exact_rc_artifact: {ok: "false"}` and an empty
`graceful_drain` record as passing. Reproduced directly on the assigned head;
all twelve new cases failed before the fix. The evaluator now requires literal
boolean `true` for a pass and an explicit boolean `required` field for drain.
Only literal `false` exempts the SIGKILL-mode run from graceful-drain success.

The tests round-trip evidence through JSON, check the pure failure list, and
exercise the actual CLI nonzero exit path with the asynchronous run replaced by
that evidence. They are evidence-validation tests, not an exact-RC soak.
Existing tests retain valid boolean pass and explicit SIGKILL exemption coverage.

Focused result after repair: 85 passed across the soak evaluator suite and
`packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`.
No package suite count changes; no shared baseline or quality ledger edits.
