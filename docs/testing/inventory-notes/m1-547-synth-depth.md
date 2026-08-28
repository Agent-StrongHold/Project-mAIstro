# M1 #547 — dispatched-only synth depth accounting

Issue #547 changes the durable graph recursion-depth evidence rule for `agent.synth_dag`.

A synthesized DAG may complete successfully as a synthesis operation while truthfully declining execution (`success=true`, `dispatched=false`). That outcome did not spawn child work and must not consume recursion depth.

The executor now treats `dispatched=true` as the sole spawn evidence for `agent.synth_dag`. Existing mutation-sensitive tests prove:

- a dispatched synthesized child increments depth exactly once;
- a truthful decline leaves depth unchanged;
- a failed child that was dispatched still counts as a spawn;
- missing dispatch evidence does not count as a spawn;
- `agent.spawn_harness` retains its existing accounting behavior.

This is an accounting-only correction. It does not change Run, NodeRun, Attempt, or child-Run lifecycle semantics.
