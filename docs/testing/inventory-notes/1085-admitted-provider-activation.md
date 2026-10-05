---
inventory-delta:
  packages/hive-conductor/backend/tests: +49
  packages/maistro-core/tests: +4
---
# 1085-admitted-provider-activation


Provider activation retains the shipped config.write/operator root scope and the
fixed provider catalogue. Its one-token health call now runs under a fresh
canonical root Run, control-plane capability Node, real requesting actor and
heartbeat-renewed expiring Attempt lease. The immutable provider-activation ID,
first-created timestamp, model pin and revocation state remain authoritative.

The configured admin registration credential is used only for internal setup;
the health probe uses the Binding-selected scoped credential. Setup follows
policy, strict model/credential selection and Invocation/quota admission. Setup
errors do not update probe credential health. Secret-bearing arbitrary exception
text and contexts cannot enter Invocation/Attempt evidence or classifier logs.
Any probe error after registration retains UNKNOWN, including connect failures.

One-shot logical failures close through legal lifecycle transitions. Actual
cancellation signals the registered Runtime promptly, drains durable writes,
and cannot mark activation successful. Admission-to-execution and repeated
terminal-write cancellations preserve existing winners. A recovered physical
Attempt remains CANCELLED while the one-shot logical operation reports FAILED;
the existing Invocation evidence is retained, with no automatic retry.

New tests use real SQLite services with terminal MockTransport and a fixture
vault. They cover authority/refusal ordering, quotas 0/1 and unknown numeric
bounds, immutable/refused/revoked Bindings, distinct admin/probe credentials,
secret-free records/logs, repeat probes, credential health, partial setup,
timeouts, cancellation and lease renewal. Four legacy provider consumer tests
retain their assertions but now obtain genuine leased execution. Actual
middleware proves ordinary/unelevated denial, admin/elevated allowance and
unchanged admin-chat denial. Age toolchain tests remain separately skippable.

Only focused hermetic tests execute locally. Suite inventory is collection-only;
no full Hive run, live gateway, live key, quality-ledger change or workflow change.
The accompanying SPEC-072726-3439 remains Proposed; this leaf preserves shipped
route/middleware authority rather than treating that document as a new grant.

After both evaluator and activation use admitted execution, the unused raw
completion wrapper and manual OperationIdentity mint/settle helpers are removed.
Three helper-only tests are retired; the new real-service activation/evaluator
suites cover unavailable canonical state and completed/failed/cancelled outcomes
with actual leased Attempts. The net inventory delta accounts for these removals.
