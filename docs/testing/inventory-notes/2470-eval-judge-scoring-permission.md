---
inventory-delta:
  packages/hive-conductor/backend/tests: +17
---
# 2470 eval-judge scoring permission

## What moved

`packages/hive-conductor/backend/tests` gains 17 collected node IDs, all in the
new `test_eval_judge_scoring_authorization.py`. `test_eval_judge.py` keeps its
36 node IDs: three trigger tests were rewritten in place (same counts) because
the #2470 route contract changed what a successful POST means — the caller now
needs the assigned-and-elevated `eval.score` capability, and the scored target
must be a terminal canonical Run rather than whatever the projection returned.

## Why

Issue #2470 separates eval-judge *scoring* (a billed model effect that
overwrites the shared verdict evidence the optimizer ranks on) from Run *read
visibility* (the #1174 Workspace-scoped inspection). The suite now pins each
gate the fix installs, at the layer that owns it:

- 2 node IDs pin the route-permission table's method split directly
  (`required_permission`) and through the real ASGI middleware (403 without
  the capability, GET untouched).
- 7 node IDs drive the two-principal same-Workspace, administrator, and
  cross-Workspace-link scenes through the real app against the canonical
  Run/Workspace/Project stores — the same rig the #2466 cancel suite uses —
  asserting refusals precede every physical effect (scorer spy stays empty,
  no verdict row, no audit-success entry), plus the five non-terminal
  statuses (parametrized) and the projection-only (no canonical Run) row.
- 4 node IDs pin the evidence contract on the service: a valid verdict is
  terminal evidence that erroring, unparseable, or unavailable attempts
  cannot downgrade; error receipts stay retryable; a valid-verdict retry
  (double-click or post-restart) returns the stored row verbatim with no new
  model invocation.
- 4 node IDs cover provenance and single-flight: the verdict carries actor/
  Workspace/evaluator-version provenance with one audited success, and two
  concurrent authorized scores join one in-flight invocation (one paid model
  effect, identical verdicts, one evidence row).

The route-level happy path in `test_eval_judge.py` additionally asserts the
verdict is keyed by the canonical Run id — not a projection alias — which is
what makes the idempotency and cross-id read guarantees above hold.
