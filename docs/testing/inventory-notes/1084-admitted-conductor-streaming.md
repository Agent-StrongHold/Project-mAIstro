---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +124
  packages/maistro-server/tests: +2
---
# Admitted conductor calls and governed streaming (#1084)

This bounded residual of stale #1370 consumes the existing Run, Binding,
Invocation, Provider and quota owners. It does not close #1084 or #56.

## Change and evidence

- `AdmittedModelCalls` resolves persisted joined Run/NodeRun/Attempt records,
  requires running leased execution, takes scope and actor from the Run and
  resolves an explicitly configured Binding on every call. It never registers
  credentials or substitutes a fabricated identity.
- Core conductor, server roster/task execution and Hive task execution use that
  adapter. Circuit admission uses the actual configured gateway and Binding pin;
  a pin cannot be bypassed by a caller fallback. Automatic transport retries require
  `EffectNotApplied`; HTTP errors/timeouts recorded UNKNOWN remain unresolved
  rather than redispatching under a different effect key. The first-dispatch `TaskAttemptExecutor` path now binds its already
  loaded persisted Run ID beside the existing Workspace/Project/NodeRun/Attempt
  context. The actual SQLite task test failed before that correction.
- Provider streaming uses the same existing Invocation executor and canonical
  usage recorder. Its [lifecycle design](../../design/1084-governed-model-streaming.md)
  covers backpressure, replay, cancellation, errors and terminal evidence.
- Streaming regressions first exposed repeated-cancellation cleanup, repeated
  tool-ID concatenation and content arriving after finish. All are covered by
  deterministic MockTransport byte streams; restart replay uses actual SQLite.
- The old raw-conductor fallback tests are replaced by fail-closed refusal and
  canonical-record transport tests. The obsolete process-global quota-tracker
  helper and its singleton test are removed; Container/Invocation quota wiring
  remains authoritative. No tests are removed to conceal an active failure.
- Only the physically removed conductor raw-call rows are pruned from the
  direct-egress/direct-effect inventories. Unmigrated Hive/Agent callers remain.

## Verification boundary

Focused tests substitute final HTTP transport with MockTransport or explicit
fake gateway boundaries. No full local Hive suite, live gateway, external
credential, workflow dispatch or workflow edit is used. Suite inventory is
collected separately; exact-head standard CI supplies broader execution proof.

The Hive public chat/voice routes, the old Agent client adapter and configured
Responses API parity are not claimed migrated by this leaf. The prepared Hive
chat cutover is held for protocol-preserving follow-up. Existing #1954–#1957
sibling leaves remain separate; this stack does not claim their combined-head
acceptance, the isolated harness boundary, installed profiles or live-provider
release proof. No merge or deployment is requested.
