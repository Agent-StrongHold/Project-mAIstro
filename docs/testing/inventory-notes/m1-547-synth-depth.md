---
inventory-delta:
  packages/maistro-core/tests: +3
---
# M1 #547 — dispatched-only synth depth accounting

Issue #547 changes the durable graph recursion-depth evidence rule for `agent.synth_dag`.

A synthesized DAG may complete successfully as a synthesis operation while truthfully declining execution (`success=true`, `dispatched=false`). That outcome did not spawn child work and must not consume recursion depth.

The executor now treats `dispatched=true` as the sole spawn evidence for `agent.synth_dag`. The durable-walk recursion tests dispatch registered child work through the real synth node and assert the persisted child Run, NodeRun result, and Attempt before using that dispatch as depth evidence. Together with the mutation-sensitive tests, they prove:

- genuinely dispatched child work increments depth exactly once;
- a truthful decline leaves depth unchanged;
- a failed child that was dispatched still counts as a spawn;
- missing dispatch evidence does not count as a spawn;
- `agent.spawn_harness` retains its existing accounting behavior.

This is an accounting-only correction. It does not change Run, NodeRun, Attempt, or child-Run lifecycle semantics.
