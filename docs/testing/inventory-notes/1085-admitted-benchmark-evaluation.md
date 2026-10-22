---
inventory-delta:
  packages/hive-conductor/backend/tests: +102
---
# Admit benchmark judgments and preserve failed-score truth (#1085, #1370)

The evaluator now executes its one-node child Run through RunExecutionService
and AttemptExecutionService, retaining the canonical service's lease, live
correlation, persisted actor, cancellation, physical evidence and logical
success contract. The child is in exactly its evaluated parent's
Workspace/Project scope and uses the registered evaluation node kind. Its
AdmittedModelCalls composition references configured Bindings covering
`benchmark-evaluation`; it creates no consumer grants and copies no ambient
credentials. Operators must configure an unambiguous matching Binding and
scoped credential through existing configuration. Provider pins remain strict.

There is no automatic evaluator retry. Canonical generic failure reconciliation
parks a failed physical Attempt pending a domain decision; this one-shot domain
closes that logical operation as failed. Authorization refusal deliberately
changes from the legacy manually minted cancelled Attempt to failed canonical
physical evidence with `error_kind=authorization`. No cancellation occurred,
so representing refusal as failed preserves the canonical distinction from an
actual requested cancellation. Cancellation still propagates as CancelledError
and fences the logical operation as cancelled. If physical completion has
already won, its completed Attempt remains immutable. Shielded admission and
terminal persistence are drained after signaling the canonical cancellation
owner; repeated cancellation cannot abandon either write. A rejected rubric fails the
operation while its already-completed model Invocation and billed usage remain
completed and recorded once. A reclaimed physical Attempt remains cancelled;
late success, malformed rubric or provider failure closes this one-shot logical
operation as failed without replaying the model effect. Requested cancellation
retains its separate cancelled disposition.

The evaluator now raises typed BenchmarkAuthorizationError or
BenchmarkEvaluationError rather than returning an error dictionary containing
`total=0`. Optimizer baseline failures stop validation and report HTTP 403 or
502. Failed candidate executions/evaluations cannot be promoted as cheaper
zero-quality models; a genuinely measured zero score retains that behavior.

Added 85 evaluator cases with real SQLite Container admission and final
httpx.MockTransport only: configured authority, immutable grants, scoped keys,
actor request budgets zero and one, missing/ambiguous/revoked/disabled/foreign
Bindings, policy/approval refusal, exact parent scope and actor, absent runtime,
lease/ancestry/terminal refusal, strict pins, invalid rubric and retained usage,
full five-criterion schema/sum validation, valid score bounds, same-effect completed replay and UNKNOWN refusal, task
cancellation and terminal-write/admission races, admission failure, and DAG
output decomposition. Seventeen
hermetic consumer cases cover typed and generic baseline errors, failed score
filtering, and preserved successful/zero-score model and parameter behavior.
Existing evaluator tests use explicit operator-configured test Bindings and
assert the typed failure contract; their collected count is unchanged.

Fail-first tests against the actual dependency base reproduced an unleased
Attempt and lack of a typed zero-quota refusal. Consumer regressions reproduced
zero-baseline continuation and promotion of an unscored cheaper candidate.
The collection-only Hive inventory grows from 3,449 to 3,551. Full local Hive
execution and live gateway access are excluded; only selected hermetic suites
run. Provider activation, tools, sandbox, public chat/Responses and unattended
Evolve admission remain separate leaves.
