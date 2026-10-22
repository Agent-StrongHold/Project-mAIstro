---
inventory-delta:
  packages/maistro-core/tests: +131
  packages/hive-conductor/backend/tests: +39
---
# Public Hive admitted model calls and protocol compatibility (#1084)

The core adds 130 collected protocol cases covering Responses completion,
streaming, refusal/reasoning/usage normalization, strict terminal evidence,
explicit operator ingress declarations and the bounded unsupported-ingress
contract. Fallback uses separate canonical Invocations under the same effect
identity and rechecks authority; UNKNOWN blocks redispatch until reconciliation.
Core source coverage is measured from core tests, independently of Hive.

Hive adds 47 admitted SQLite/MockTransport cases and removes eight obsolete
raw-adapter/normalizer cases (net +39). The retired raw complete/stream pooling,
headers and Responses normalization cases are replaced by governed equivalents;
the old bare-404 fallback expectation is replaced by explicit unsupported proof
versus ambiguous refusal. Existing route/admission/voice assertions remain,
with fixtures declaring actual scoped model authority. The setup/probe core
fixture import moves to its existing shared home so the Agent and activation
leaves compose without changing any assertion.

The tests cover persisted actor/Workspace/Project/lease/Binding authority,
completed replay and later Attempts, UNKNOWN and explicit reconciliation,
distinct completed correction/continuation/synthesis effects, distinct dashboard
tool positions, declared vision protocol and timeout, cancellation/stream close,
public conversation containment, failure frames, and fail-closed composition.
Only terminal HTTP uses MockTransport; no full local Hive suite or live gateway
is executed. PostgreSQL/accounting reconciliation proof has its separate additive
inventory note and does not become duplicated evidence here.

Independent review added two Hive end-to-end regressions and one core stream
regression for multi-tool replay. Completed tool lists must reconstruct distinct
stream indices in original order without mutating persisted results. The former
index collapse changed trusted tool positions and could escape a previous
UNKNOWN dashboard effect; both completed and uncertain replay now retain the
same logical keys and make no duplicate model call.

Six protocol cases prove Provider-owned actual-ingress evidence, upstream marker
spoofing refusal, and recorded replay after capability configuration changes.
UNKNOWN and historic unmarked outcomes are not given fabricated lane evidence.
